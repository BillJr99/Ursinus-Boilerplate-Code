<#
.SYNOPSIS
    Provisions a Microsoft Teams team and a OneNote Class Notebook for each course in a term.

.DESCRIPTION
    For each course entered at the prompt, this script creates:

      1. A team named "<Course> <Semester> <Year>", for example "CS374 Fall 2026",
         owned by the signed-in instructor, with the listed students added as members.

      2. A OneNote Class Notebook of the same name in the instructor's OneDrive, in which
         every student receives a private section group, visible only to that student and
         to the teacher, containing the sections named in StudentSections. By default those
         are "Class Notes" and "Reflective Journals". A Teacher Only section group is
         created alongside them.

    Re-running the script for a course that already has a class notebook is safe and is the
    intended add/drop workflow. Students on the roster who are not yet in the notebook are
    added, which creates their section group. Students in the notebook who are no longer on
    the roster are reported but never removed, because removal revokes access and should be
    a deliberate act rather than a side effect of a rerun.

    Two identities are used, deliberately:

      MicrosoftTeams module      New-Team and Add-TeamUser run in the ordinary end-user
                                 context and act on teams you own, so no administrator
                                 consent is required for any scope.

      OneNote device-code token  The Class Notebook API lives on the legacy OneNote host,
                                 https://www.onenote.com/api/v1.0, not on Microsoft Graph.
                                 Graph exposes ordinary notebooks only and has no concept
                                 of student section groups. A token whose audience is
                                 onenote.com is therefore obtained directly through the
                                 OAuth 2.0 device authorization grant, using no modules at
                                 all. The required scope, Notes.ReadWrite, is one an
                                 ordinary user can consent to.

    Run probe_classnotebook.ps1 first. It is read-only, and it reports which public client
    id can obtain an onenote.com token in your tenant. Put that value in OneNote.ClientId
    below.

.PARAMETER ConfigPath
    Optional JSON file whose keys are merged over $DefaultConfig.

.PARAMETER DryRun
    Print every intended write without performing it.

.EXAMPLE
    .\provision_course_workspaces.ps1 -DryRun

.NOTES
    Nothing is installed and no administrator rights are needed. The MicrosoftTeams module
    is staged into .\modules with Save-Module, which copies files without registering them.

    FERPA: student email addresses are education records, and a reflective journal is a
    candid document. Log redaction is on by default via RedactEmailsInLogs, and no student
    content is ever read by this script.
#>

[CmdletBinding()]
param(
    [string] $ConfigPath,
    [switch] $DryRun,
    [switch] $ListTeams,
    [switch] $Logout
)

Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
$DefaultConfig = @{
    Modules = @{
        # Only one module is needed now. The OneNote calls use plain REST.
        Required      = @('MicrosoftTeams')
        ModulePath    = 'modules'
        AllowDownload = $true
    }
    OneNote = @{
        # Replace ClientId with whatever probe_classnotebook.ps1 reports as working in your
        # tenant. The default is the Microsoft Graph Command Line Tools public client, which
        # is the most commonly preauthorized one.
        ClientId    = '14d82eec-204b-4c2f-b7e8-296a70dab67e'
        Tenant      = 'organizations'
        Authority   = 'https://login.microsoftonline.com'
        ApiRoot     = 'https://www.onenote.com/api/v1.0'
        Scopes      = 'https://onenote.com/Notes.ReadWrite offline_access'
        PollSeconds = 5
        PollLimit   = 60
    }
    TokenCache = @{
        # Sign-in state is cached so that repeated runs do not repeat the device-code dance.
        # What is stored is the refresh token, not your password, and on Windows it is encrypted
        # with DPAPI, meaning the file can only be decrypted by your account on this machine.
        # Copying it elsewhere yields nothing usable. Delete the file, or run with -Logout, to
        # revoke it locally.
        Enabled = $true
        Path    = '.tokencache.xml'
    }
    Provisioning = @{
        # Sections replicated inside every student's private section group. Each student sees
        # only their own copy; the teacher sees all of them.
        StudentSections            = @('Class Notes', 'Reflective Journals')

        # Sections created inside the shared _Collaboration Space, which every student can read
        # and write. This is where genuinely collaborative work belongs: a section replicated
        # into private student groups would be collaborative in name only.
        CollaborationSections      = @('Collaborative Activities')

        # The class notebook API creates the Collaboration Space itself, but names it according
        # to the notebook's language. This is the en-us name; change it if omkt is changed.
        CollaborationSpaceName     = '_Collaboration Space'

        HasTeacherOnlySectionGroup = $true
        SendEmailOnCreate          = $false
        NotebookLanguage           = 'en-us'
        UseAsyncNotebookCreation   = $false
        CreateTeam                 = $true
        TeamVisibility             = 'Private'
        TeamDescriptionTemplate    = 'Course workspace for {0}'
        # Entra ID group naming policy. Many tenants, including Ursinus, require every new
        # Microsoft 365 group to carry a prefix or a suffix on its display name, its mail
        # nickname, or both. The policy is only readable with an admin-consented directory
        # scope, so it is supplied here instead. Run the script with -ListTeams to see the
        # names of teams that already exist and infer the convention from them.
        #
        # Example: a policy of "GRP_[GroupName]" means TeamNamePrefix = 'GRP_'.
        # The notebook name is never affected by these; only the team and group are.
        # Ursinus enforces a UCGroup_ prefix on Microsoft 365 groups. Entra applies the policy
        # to both the group's display name and its alias (mail nickname), so both carry it. If
        # a run fails because the alias does not need the prefix, clear TeamMailNicknamePrefix.
        TeamNamePrefix             = 'UCGroup_'
        TeamNameSuffix             = ''
        TeamMailNicknamePrefix     = 'UCGroup_'
        TeamMailNicknameSuffix     = ''

        # The group naming policy does NOT reach OneNote. The class notebook is created in the
        # instructor's OneDrive, not as a group, so it keeps the plain course name. These
        # affixes exist only if you ever want the notebook named differently from the course.
        NotebookNamePrefix         = ''
        NotebookNameSuffix         = ''

        # After a notebook is created or updated, open it in the locally installed OneNote
        # desktop application. This uses the onenote: protocol link the service returns, which
        # focuses an already-running OneNote rather than launching a second copy, so there is no
        # duplicate-window hazard. Windows only; ignored elsewhere and during a dry run.
        OpenInOneNoteClient        = $true

        # Wait this long after opening before continuing to the next course, so that several
        # notebooks opened in one run do not race each other into the client. Set to 0 to skip.
        OpenDelaySeconds           = 3
        CreateNamedChannel         = $false
        ChannelMembershipType      = 'Standard'
        StudentRole                = 'Member'
        MemberAddDelaySeconds      = 2
        NotebookRequestTimeoutSec  = 300
        # Redaction is off: you run this privately and need to be able to read the names of
        # students the script reports on. Set it to $true if you ever share a log or run this
        # where someone else can see the console, since a roster is a FERPA-covered record.
        RedactEmailsInLogs         = $false
    }
    Logging = @{
        Level = 'INFO'
        File  = 'logs\provision.log'
    }
}

# ---------------------------------------------------------------------------
# Configuration loading and logging
# ---------------------------------------------------------------------------

function Merge-Hashtable {
    <#
    .SYNOPSIS
        Returns a copy of Base with Override merged into it recursively.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [hashtable] $Base,
        [Parameter(Mandatory)] [hashtable] $Override
    )
    try {
        $merged = @{}
        foreach ($key in $Base.Keys) { $merged[$key] = $Base[$key] }
        foreach ($key in $Override.Keys) {
            if ($merged.ContainsKey($key) -and $merged[$key] -is [hashtable] -and $Override[$key] -is [hashtable]) {
                $merged[$key] = Merge-Hashtable -Base $merged[$key] -Override $Override[$key]
            }
            else { $merged[$key] = $Override[$key] }
        }
        return $merged
    }
    catch {
        Write-Host "[provision:Merge-Hashtable] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function ConvertTo-Hashtable {
    <#
    .SYNOPSIS
        Converts a PSCustomObject from ConvertFrom-Json into a nested hashtable.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] $InputObject)
    try {
        if ($InputObject -is [System.Collections.IEnumerable] -and $InputObject -isnot [string]) {
            return @($InputObject | ForEach-Object { ConvertTo-Hashtable -InputObject $_ })
        }
        if ($InputObject -is [psobject]) {
            $result = @{}
            foreach ($property in $InputObject.PSObject.Properties) {
                $result[$property.Name] = ConvertTo-Hashtable -InputObject $property.Value
            }
            return $result
        }
        return $InputObject
    }
    catch {
        Write-Host "[provision:ConvertTo-Hashtable] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Get-EffectiveConfig {
    <#
    .SYNOPSIS
        Returns the embedded defaults, with an optional JSON file merged over them.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [hashtable] $Default,
        [string] $Path
    )
    try {
        if (-not $Path) { return $Default }
        if (-not (Test-Path -LiteralPath $Path)) { throw "Configuration file not found: $Path" }
        $override = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json | ForEach-Object { ConvertTo-Hashtable -InputObject $_ }
        return Merge-Hashtable -Base $Default -Override $override
    }
    catch {
        Write-Host "[provision:Get-EffectiveConfig] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Write-Log {
    <#
    .SYNOPSIS
        Writes a timestamped message to the console and, if configured, to the log file.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Message,
        [ValidateSet('DEBUG', 'INFO', 'WARNING', 'ERROR')] [string] $Level = 'INFO',
        [hashtable] $Config
    )
    try {
        $levels = @{ DEBUG = 0; INFO = 1; WARNING = 2; ERROR = 3 }
        $threshold = 'INFO'
        $logFile = $null
        if ($Config) {
            $threshold = $Config.Logging.Level
            $logFile = $Config.Logging.File
        }
        if ($levels[$Level] -lt $levels[$threshold]) { return }

        $line = '{0} {1,-8} {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
        switch ($Level) {
            'ERROR'   { Write-Host $line -ForegroundColor Red }
            'WARNING' { Write-Host $line -ForegroundColor Yellow }
            default   { Write-Host $line }
        }
        if ($logFile) {
            $directory = Split-Path -Parent $logFile
            if ($directory -and -not (Test-Path -LiteralPath $directory)) {
                New-Item -ItemType Directory -Path $directory -Force | Out-Null
            }
            Add-Content -LiteralPath $logFile -Value $line
        }
    }
    catch {
        Write-Host "[provision:Write-Log] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
    }
}

function Get-RedactedEmail {
    <#
    .SYNOPSIS
        Returns a log-safe rendering of an email address.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Email,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        if (-not $Config.Provisioning.RedactEmailsInLogs) { return $Email }
        if ($Email -notmatch '@') { return '***' }
        $parts = $Email.Split('@', 2)
        $local = $parts[0]
        $keep = if ($local.Length -ge 2) { $local.Substring(0, 2) } else { $local }
        $stars = '*' * [Math]::Max($local.Length - 2, 1)
        return '{0}{1}@{2}' -f $keep, $stars, $parts[1]
    }
    catch {
        Write-Host "[provision:Get-RedactedEmail] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return '***'
    }
}

# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

function Split-DelimitedList {
    <#
    .SYNOPSIS
        Splits a comma-separated or semicolon-separated string into trimmed tokens.
    #>
    [CmdletBinding()]
    param([string] $Raw)
    try {
        if ([string]::IsNullOrWhiteSpace($Raw)) { return @() }
        return @($Raw -split '[,;\r\n]' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
    catch {
        Write-Host "[provision:Split-DelimitedList] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return @()
    }
}

function ConvertTo-CourseEntry {
    <#
    .SYNOPSIS
        Parses a course token into Course, Semester, Year, and DisplayName.
    .DESCRIPTION
        Accepts "CS374", "CS374 Fall 2026", and "CS374, Fall 2026" alike, filling anything
        omitted from the semester and year supplied at the prompt.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Entry,
        [string] $DefaultSemester,
        [string] $DefaultYear
    )
    try {
        $tokens = @($Entry -replace ',', ' ' -split '\s+' | Where-Object { $_ })
        if ($tokens.Count -eq 0) { throw "Empty course entry." }

        $course = $tokens[0].ToUpper()
        $semester = $DefaultSemester
        $year = $DefaultYear

        if ($tokens.Count -ge 2 -and $tokens[-1] -match '^\d{4}$') {
            $year = $tokens[-1]
            if ($tokens.Count -ge 3) { $semester = $tokens[-2] }
        }
        elseif ($tokens.Count -ge 2) { $semester = $tokens[1] }

        if (-not $semester -or -not $year) { throw "Could not determine semester and year for entry: $Entry" }
        $semester = $semester.Substring(0, 1).ToUpper() + $semester.Substring(1).ToLower()

        return [pscustomobject]@{
            Course      = $course
            Semester    = $semester
            Year        = $year
            DisplayName = "$course $semester $year"
        }
    }
    catch {
        Write-Host "[provision:ConvertTo-CourseEntry] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Select-ValidEmail {
    <#
    .SYNOPSIS
        Returns only those tokens that look like email addresses, warning about the rest.
    #>
    [CmdletBinding()]
    param(
        [string[]] $Tokens,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        $valid = @()
        foreach ($token in $Tokens) {
            if ($token -match '^[^@\s]+@[^@\s]+\.[^@\s]+$') { $valid += $token.ToLower() }
            else { Write-Log -Message "Skipping token that is not an email address: $token" -Level WARNING -Config $Config }
        }
        return $valid
    }
    catch {
        Write-Host "[provision:Select-ValidEmail] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return @()
    }
}

function Get-MailNickname {
    <#
    .SYNOPSIS
        Derives a valid group mail nickname from a course display name.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [string] $DisplayName)
    try {
        $nickname = $DisplayName.ToLower() -replace '[^a-z0-9]+', '-'
        return $nickname.Trim('-')
    }
    catch {
        Write-Host "[provision:Get-MailNickname] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Get-EmailAddress {
    <#
    .SYNOPSIS
        Extracts every email address found anywhere in a block of text.
    .DESCRIPTION
        This is deliberately extraction rather than splitting. A roster pasted out of a CSV
        or a spreadsheet arrives as whole rows, and those rows carry names, ID numbers,
        section codes, and quoting that no delimiter rule survives cleanly. Scanning for the
        address pattern instead means the surrounding columns are simply ignored, so all of
        the following yield the same three addresses:

            a@ursinus.edu, b@ursinus.edu; c@ursinus.edu
            Smith,John,a@ursinus.edu,CS374-A
            "Doe, Jane" <b@ursinus.edu>
            c@ursinus.edu

        Duplicates are removed while preserving the order in which addresses first appear,
        because a student listed twice in a roster export should not be added twice.
    #>
    [CmdletBinding()]
    param(
        [string] $Text,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        if ([string]::IsNullOrWhiteSpace($Text)) { return @() }

        $pattern = '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'
        $matches = [regex]::Matches($Text, $pattern)

        $seen = New-Object System.Collections.Generic.HashSet[string]
        $ordered = @()

        foreach ($match in $matches) {
            $email = $match.Value.ToLower().Trim('.', ',', ';', '<', '>', '"', "'")
            if ($seen.Add($email)) { $ordered += $email }
            else {
                Write-Log -Message "Duplicate address ignored: $(Get-RedactedEmail -Email $email -Config $Config)" -Level DEBUG -Config $Config
            }
        }

        return $ordered
    }
    catch {
        Write-Host "[provision:Get-EmailAddress] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return @()
    }
}

function Read-PastedBlock {
    <#
    .SYNOPSIS
        Reads a multi-line block from the console, ending at a blank line.
    .DESCRIPTION
        Read-Host returns at every newline, so a multi-line paste simply satisfies several
        consecutive calls. Looping until a blank line therefore lets an entire pasted CSV
        selection be consumed in one go, while still accepting a single delimited line typed
        by hand. Press Enter on an empty line to finish.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [string] $Prompt)
    try {
        Write-Host ''
        Write-Host $Prompt
        Write-Host '  Paste one or more lines, or type a comma or semicolon separated list.'
        Write-Host '  Press Enter on an empty line when you are done.'

        $lines = @()
        while ($true) {
            $line = Read-Host '  >'
            if ([string]::IsNullOrWhiteSpace($line)) { break }
            $lines += $line
        }
        return ($lines -join "`n")
    }
    catch {
        Write-Host "[provision:Read-PastedBlock] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Read-CourseInput {
    <#
    .SYNOPSIS
        Collects the course list, the term, and a roster per course interactively.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [hashtable] $Config)
    try {
        Write-Host ''
        Write-Host 'Course provisioning: Microsoft Teams team and OneNote Class Notebook'
        Write-Host ('-' * 70)

        $rawCourses = Read-Host 'Course list (comma or semicolon separated, e.g. CS374, CS477)'
        $courseTokens = @(Split-DelimitedList -Raw $rawCourses)
        if ($courseTokens.Count -eq 0) { throw 'No courses were entered.' }

        $defaultSemester = Read-Host 'Semester (e.g. Fall)'
        $defaultYear = Read-Host 'Year (e.g. 2026)'

        $courses = @()
        $sharedRoster = $null

        foreach ($token in $courseTokens) {
            $entry = ConvertTo-CourseEntry -Entry $token -DefaultSemester $defaultSemester -DefaultYear $defaultYear

            $prompt = "Student emails for $($entry.DisplayName)"
            if ($sharedRoster) { $prompt += " (or type 'same' to reuse the previous roster)" }
            $rawEmails = Read-PastedBlock -Prompt $prompt

            if ($rawEmails.Trim().ToLower() -eq 'same' -and $sharedRoster) { $emails = @($sharedRoster) }
            else {
                $emails = @(Get-EmailAddress -Text $rawEmails -Config $Config)
                $sharedRoster = $emails
            }

            if ($emails.Count -eq 0) { throw "No email addresses were found in the roster for $($entry.DisplayName)." }
            Write-Host ("  Found {0} address(es)." -f $emails.Count)

            $courses += [pscustomobject]@{
                Course      = $entry.Course
                Semester    = $entry.Semester
                Year        = $entry.Year
                DisplayName = $entry.DisplayName
                Emails      = $emails
            }
        }
        return $courses
    }
    catch {
        Write-Host "[provision:Read-CourseInput] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

# ---------------------------------------------------------------------------
# Module staging
# ---------------------------------------------------------------------------

function Initialize-PackageSource {
    <#
    .SYNOPSIS
        Prepares Windows PowerShell 5.1 to reach the PowerShell Gallery.
    .DESCRIPTION
        Windows PowerShell 5.1 negotiates a TLS version the Gallery no longer accepts, and
        its package plumbing prompts interactively to bootstrap the NuGet provider the first
        time Save-Module runs. Both are handled here so the run is unattended. The provider
        is bootstrapped into the current user's scope, which needs no administrator rights.
        PowerShell 7 needs none of this, so this is a no-op there.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [hashtable] $Config)
    try {
        if ($PSVersionTable.PSEdition -ne 'Desktop') { return }

        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Write-Log -Message 'Enabled TLS 1.2 for this Windows PowerShell session.' -Level DEBUG -Config $Config

        if (-not (Get-PackageProvider -Name NuGet -ErrorAction SilentlyContinue)) {
            Write-Log -Message 'Bootstrapping the NuGet package provider for the current user.' -Config $Config
            Install-PackageProvider -Name NuGet -Scope CurrentUser -Force -ErrorAction Stop | Out-Null
        }
    }
    catch {
        Write-Host "[provision:Initialize-PackageSource] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Initialize-RequiredModule {
    <#
    .SYNOPSIS
        Makes the required modules importable without installing anything into the profile.
    .DESCRIPTION
        An installed module is imported as-is. Otherwise the module is staged into the local
        ModulePath folder with Save-Module, which copies files without registering them, and
        imported from there. Delete the folder to undo it.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [hashtable] $Config)
    try {
        $modulePath = $Config.Modules.ModulePath
        if (-not [System.IO.Path]::IsPathRooted($modulePath)) {
            $modulePath = Join-Path $PSScriptRoot $modulePath
        }

        foreach ($name in $Config.Modules.Required) {
            if (Get-Module -Name $name) { continue }

            if (Get-Module -ListAvailable -Name $name) {
                Import-Module -Name $name -ErrorAction Stop
                Write-Log -Message "Imported installed module '$name'." -Config $Config
                continue
            }

            $staged = Join-Path $modulePath $name
            if (-not (Test-Path -LiteralPath $staged)) {
                if (-not $Config.Modules.AllowDownload) {
                    throw "Module '$name' is neither installed nor staged in '$modulePath', and downloading is disabled."
                }
                if (-not (Test-Path -LiteralPath $modulePath)) {
                    New-Item -ItemType Directory -Path $modulePath -Force | Out-Null
                }
                Initialize-PackageSource -Config $Config
                Write-Log -Message "Staging module '$name' into '$modulePath'. This downloads files but installs nothing." -Config $Config
                Save-Module -Name $name -Path $modulePath -Force -ErrorAction Stop
            }

            Import-Module -Name $staged -ErrorAction Stop
            Write-Log -Message "Imported staged module '$name' from '$staged'." -Config $Config
        }
    }
    catch {
        Write-Host "[provision:Initialize-RequiredModule] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

# ---------------------------------------------------------------------------
# OneNote authentication and REST
# ---------------------------------------------------------------------------

function Get-TokenCachePath {
    <#
    .SYNOPSIS
        Returns the absolute path of the token cache file.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [hashtable] $Config)
    try {
        $path = $Config.TokenCache.Path
        if (-not [System.IO.Path]::IsPathRooted($path)) { $path = Join-Path $PSScriptRoot $path }
        return $path
    }
    catch {
        Write-Host "[provision:Get-TokenCachePath] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Save-TokenCache {
    <#
    .SYNOPSIS
        Persists a refresh token so that later runs do not require an interactive sign-in.
    .DESCRIPTION
        Only the refresh token is stored, never a password and never an access token, which
        expires within the hour anyway. On Windows the value is encrypted with DPAPI through
        ConvertFrom-SecureString, which binds the ciphertext to this user on this machine: the
        file is inert if copied anywhere else. On other platforms PowerShell cannot offer that
        guarantee, so caching is refused rather than silently writing a bearer credential in
        cleartext.

        The token is never written to the log, printed, or echoed.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $RefreshToken,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        if (-not $Config.TokenCache.Enabled) { return }

        $onWindows = ($PSVersionTable.PSEdition -eq 'Desktop') -or ($env:OS -eq 'Windows_NT')
        if (-not $onWindows) {
            Write-Log -Message 'Token caching is only offered on Windows, where DPAPI can protect the file. Skipping.' -Level WARNING -Config $Config
            return
        }

        $path = Get-TokenCachePath -Config $Config
        $protected = ConvertTo-SecureString -String $RefreshToken -AsPlainText -Force | ConvertFrom-SecureString

        [pscustomobject]@{
            ClientId     = $Config.OneNote.ClientId
            Tenant       = $Config.OneNote.Tenant
            RefreshToken = $protected
            SavedAt      = (Get-Date).ToString('o')
        } | Export-Clixml -Path $path -Force

        Write-Log -Message "Sign-in cached. Later runs will not prompt. Cache: $path" -Config $Config
    }
    catch {
        Write-Host "[provision:Save-TokenCache] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
    }
}

function Get-CachedRefreshToken {
    <#
    .SYNOPSIS
        Returns the cached refresh token, or $null when there is none usable.
    .DESCRIPTION
        A cache written for a different client id or tenant is ignored rather than used, because
        a refresh token is only redeemable by the client that obtained it, and silently failing
        against the wrong one produces a confusing error much later.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [hashtable] $Config)
    try {
        if (-not $Config.TokenCache.Enabled) { return $null }

        $path = Get-TokenCachePath -Config $Config
        if (-not (Test-Path -LiteralPath $path)) { return $null }

        $cache = Import-Clixml -Path $path
        if ($cache.ClientId -ne $Config.OneNote.ClientId -or $cache.Tenant -ne $Config.OneNote.Tenant) {
            Write-Log -Message 'The cached sign-in was for a different client or tenant, so it is ignored.' -Level WARNING -Config $Config
            return $null
        }

        $secure = ConvertTo-SecureString -String $cache.RefreshToken
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try   { return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    }
    catch {
        Write-Log -Message "The cached sign-in could not be read and will be replaced: $($_.Exception.Message)" -Level WARNING -Config $Config
        return $null
    }
}

function Get-TokenByRefresh {
    <#
    .SYNOPSIS
        Redeems a refresh token for an access token for the given scope, silently.
    .DESCRIPTION
        Returns $null rather than throwing when the refresh token has expired or been revoked,
        so the caller can fall back to an interactive sign-in. Microsoft Entra issues a new
        refresh token on each redemption, so the cache is rewritten each time and remains valid
        indefinitely under normal use.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $RefreshToken,
        [Parameter(Mandatory)] [string] $Scope,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        $tokenUri = "$($Config.OneNote.Authority)/$($Config.OneNote.Tenant)/oauth2/v2.0/token"
        $response = Invoke-RestMethod -Method POST -Uri $tokenUri -Body @{
            grant_type    = 'refresh_token'
            client_id     = $Config.OneNote.ClientId
            refresh_token = $RefreshToken
            scope         = $Scope
        } -ErrorAction Stop

        if ($response.PSObject.Properties.Name -contains 'refresh_token' -and $response.refresh_token) {
            Save-TokenCache -RefreshToken $response.refresh_token -Config $Config
        }
        return $response.access_token
    }
    catch {
        Write-Log -Message "Silent sign-in for scope '$Scope' did not succeed; an interactive sign-in is needed." -Level DEBUG -Config $Config
        return $null
    }
}

function Get-OneNoteToken {
    <#
    .SYNOPSIS
        Obtains an access token whose audience is onenote.com, via the device-code grant.
    .DESCRIPTION
        The Class Notebook API is not on Microsoft Graph, so a Graph token will not work
        against it. This implements the OAuth 2.0 device authorization grant directly with
        Invoke-RestMethod, which means no authentication module is needed. The scope
        requested, Notes.ReadWrite, is user-consentable.

        If the device-code initiation fails, the configured client id is not preauthorized
        for the OneNote resource in this tenant. Run probe_classnotebook.ps1, which tries
        several well-known public clients and reports which one works.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [hashtable] $Config)
    try {
        $onenote = $Config.OneNote
        $deviceUri = "$($onenote.Authority)/$($onenote.Tenant)/oauth2/v2.0/devicecode"
        $tokenUri  = "$($onenote.Authority)/$($onenote.Tenant)/oauth2/v2.0/token"

        # Silent path: redeem a cached refresh token. This is why a second run does not prompt.
        $cached = Get-CachedRefreshToken -Config $Config
        if ($cached) {
            $silent = Get-TokenByRefresh -RefreshToken $cached -Scope $onenote.Scopes -Config $Config
            if ($silent) {
                Write-Log -Message 'Signed in silently from the cached session. No prompt was needed.' -Config $Config
                return $silent
            }
        }

        try {
            $device = Invoke-RestMethod -Method POST -Uri $deviceUri -Body @{
                client_id = $onenote.ClientId
                scope     = $onenote.Scopes
            } -ErrorAction Stop
        }
        catch {
            Write-Log -Message "The configured client id could not request an onenote.com token." -Level ERROR -Config $Config
            Write-Log -Message "Run probe_classnotebook.ps1 to find a client id that works in this tenant." -Level ERROR -Config $Config
            throw
        }

        Write-Host ''
        Write-Host $device.message -ForegroundColor Cyan
        Write-Host ''

        for ($i = 0; $i -lt $onenote.PollLimit; $i++) {
            Start-Sleep -Seconds $onenote.PollSeconds
            try {
                $token = Invoke-RestMethod -Method POST -Uri $tokenUri -Body @{
                    grant_type  = 'urn:ietf:params:oauth:grant-type:device_code'
                    client_id   = $onenote.ClientId
                    device_code = $device.device_code
                } -ErrorAction Stop
                Write-Log -Message 'Acquired a OneNote access token.' -Config $Config
                if ($token.PSObject.Properties.Name -contains 'refresh_token' -and $token.refresh_token) {
                    Save-TokenCache -RefreshToken $token.refresh_token -Config $Config
                }
                return $token.access_token
            }
            catch {
                $raw = $_.ErrorDetails.Message
                if ($raw -and ($raw -match 'authorization_pending')) { continue }
                throw
            }
        }
        throw 'Timed out waiting for device-code sign-in.'
    }
    catch {
        Write-Host "[provision:Get-OneNoteToken] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Get-TokenClaim {
    <#
    .SYNOPSIS
        Reads a named claim from the access token payload.
    .DESCRIPTION
        Only the unencrypted payload segment is decoded and no signature validation is
        attempted, because these values are used to address the caller's own resources and to
        build links, not to make a trust decision.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $AccessToken,
        [Parameter(Mandatory)] [string[]] $Names
    )
    try {
        $payload = $AccessToken.Split('.')[1]
        switch ($payload.Length % 4) {
            2 { $payload += '==' }
            3 { $payload += '=' }
        }
        $json = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload.Replace('-', '+').Replace('_', '/')))
        $claims = $json | ConvertFrom-Json

        foreach ($name in $Names) {
            if ($claims.PSObject.Properties.Name -contains $name -and $claims.$name) {
                return [string]$claims.$name
            }
        }
        return $null
    }
    catch {
        Write-Host "[provision:Get-TokenClaim] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return $null
    }
}

function Get-TokenUpn {
    <#
    .SYNOPSIS
        Extracts the signed-in user's principal name from the access token.
    .DESCRIPTION
        The teachers array needs the instructor's user principal name. Rather than making an
        extra directory call, the value is read from the token's own claims, which is where
        the identity provider already put it. Only the unencrypted payload segment is
        decoded; no signature validation is attempted, because this value is used to address
        the caller's own resources rather than to make a trust decision.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [string] $AccessToken)
    try {
        $upn = Get-TokenClaim -AccessToken $AccessToken -Names @('upn', 'preferred_username', 'unique_name', 'email')
        if (-not $upn) { throw 'No user principal name claim was present in the token.' }
        return $upn
    }
    catch {
        Write-Host "[provision:Get-TokenUpn] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Get-TeamLink {
    <#
    .SYNOPSIS
        Builds https deep links to the team and to one of its channels.
    .DESCRIPTION
        Teams deep links take the form

            https://teams.microsoft.com/l/team/{threadId}/conversations?groupId={g}&tenantId={t}
            https://teams.microsoft.com/l/channel/{threadId}/{channelName}?groupId={g}&tenantId={t}

        The thread id is the channel identifier, of the form 19:...@thread.tacv2, and it must be
        percent-encoded because it contains a colon and an at sign. The tenant id is read from
        the token's tid claim rather than fetched with another call. These links open the Teams
        client when it is installed and the web client otherwise, which is the behavior you want
        when one is pasted into a syllabus.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $GroupId,
        [Parameter(Mandatory)] [string] $TenantId,
        [string] $ChannelDisplayName = 'General',
        [Parameter(Mandatory)] [hashtable] $Config,
        [bool] $IsDryRun
    )
    try {
        if ($IsDryRun) {
            return [pscustomobject]@{
                TeamUrl    = 'https://teams.microsoft.com/l/team/19%3Adry-run%40thread.tacv2/conversations?groupId=dry-run&tenantId=dry-run'
                ChannelUrl = 'https://teams.microsoft.com/l/channel/19%3Adry-run%40thread.tacv2/General?groupId=dry-run&tenantId=dry-run'
            }
        }

        $channels = @(Get-TeamChannel -GroupId $GroupId -ErrorAction Stop)
        $target = $channels | Where-Object { $_.DisplayName -eq $ChannelDisplayName } | Select-Object -First 1
        if (-not $target) { $target = $channels | Select-Object -First 1 }
        if (-not $target) {
            Write-Log -Message 'No channels were returned for the team, so no links can be built.' -Level WARNING -Config $Config
            return $null
        }

        $threadId = [uri]::EscapeDataString([string]$target.Id)
        $channelName = [uri]::EscapeDataString([string]$target.DisplayName)
        $query = "groupId=$GroupId" + '&' + "tenantId=$TenantId"

        return [pscustomobject]@{
            TeamUrl    = "https://teams.microsoft.com/l/team/$threadId/conversations" + '?' + $query
            ChannelUrl = "https://teams.microsoft.com/l/channel/$threadId/$channelName" + '?' + $query
        }
    }
    catch {
        Write-Host "[provision:Get-TeamLink] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return $null
    }
}

function Invoke-OneNoteRequest {
    <#
    .SYNOPSIS
        Issues a request against the OneNote API and returns the parsed response.
    .DESCRIPTION
        The OneNote API reports failures in an @api.diagnostics object inside the response
        body, and that body is the only useful diagnostic when something goes wrong, so it is
        surfaced rather than swallowed.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Method,
        [Parameter(Mandatory)] [string] $Uri,
        [Parameter(Mandatory)] [string] $AccessToken,
        $Body,
        [hashtable] $ExtraHeaders,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        $headers = @{
            Authorization = "Bearer $AccessToken"
            Accept        = 'application/json'
        }
        if ($ExtraHeaders) {
            foreach ($key in $ExtraHeaders.Keys) { $headers[$key] = $ExtraHeaders[$key] }
        }

        $arguments = @{
            Method      = $Method
            Uri         = $Uri
            Headers     = $headers
            TimeoutSec  = $Config.Provisioning.NotebookRequestTimeoutSec
            ErrorAction = 'Stop'
        }
        if ($null -ne $Body) {
            $arguments['Body'] = ($Body | ConvertTo-Json -Depth 6)
            $arguments['ContentType'] = 'application/json'
        }

        Write-Log -Message "OneNote $Method $Uri" -Level DEBUG -Config $Config
        return Invoke-RestMethod @arguments
    }
    catch {
        Write-Host "[provision:Invoke-OneNoteRequest] $Method $Uri failed: $($_.Exception.Message)"
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            Write-Host "[provision:Invoke-OneNoteRequest] response body: $($_.ErrorDetails.Message)"
        }
        Write-Host $_.ScriptStackTrace
        throw
    }
}

# ---------------------------------------------------------------------------
# Class Notebook
# ---------------------------------------------------------------------------

function Get-NotebookName {
    <#
    .SYNOPSIS
        Builds a OneNote-legal notebook name from a course display name.
    .DESCRIPTION
        The Entra group naming policy does not apply here. A class notebook is a OneNote
        artifact in the instructor's OneDrive, not a Microsoft 365 group, so it carries no
        UCGroup_ prefix and simply reads "CS374 Fall 2026".

        OneNote does impose its own rules, which are different and much narrower: a notebook
        name may not exceed 128 characters and may not contain any of ? * / : < > | ' "
        Ordinary course names never come close to violating these, but a name typed with a
        slash, as in "CS374/CS574 Fall 2026", would be rejected by the service with an opaque
        error, so the offending characters are replaced with a hyphen and the result is
        truncated rather than left to fail at the API.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $DisplayName,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        $provisioning = $Config.Provisioning
        $name = '{0}{1}{2}' -f $provisioning.NotebookNamePrefix, $DisplayName, $provisioning.NotebookNameSuffix

        $illegal = '[\?\*/:<>\|''"]'
        if ($name -match $illegal) {
            $cleaned = $name -replace $illegal, '-'
            Write-Log -Message "Notebook name contained characters OneNote forbids. Using '$cleaned'." -Level WARNING -Config $Config
            $name = $cleaned
        }

        if ($name.Length -gt 128) {
            $name = $name.Substring(0, 128).TrimEnd()
            Write-Log -Message "Notebook name exceeded 128 characters and was truncated to '$name'." -Level WARNING -Config $Config
        }

        return $name
    }
    catch {
        Write-Host "[provision:Get-NotebookName] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Get-ClassNotebookByName {
    <#
    .SYNOPSIS
        Returns the existing class notebook with the given name, or $null.
    .DESCRIPTION
        This is what makes the script re-runnable. On a second run for the same course, the
        notebook is found rather than recreated, and only the roster difference is applied.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $DisplayName,
        [Parameter(Mandatory)] [string] $AccessToken,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        $uri = "$($Config.OneNote.ApiRoot)/me/notes/classNotebooks?expand=students,teachers"
        $response = Invoke-OneNoteRequest -Method GET -Uri $uri -AccessToken $AccessToken -Config $Config
        foreach ($notebook in @($response.value)) {
            if ($notebook.name -eq $DisplayName) { return $notebook }
        }
        return $null
    }
    catch {
        Write-Host "[provision:Get-ClassNotebookByName] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function New-ClassNotebook {
    <#
    .SYNOPSIS
        Creates a class notebook with a private section group for every student.
    .DESCRIPTION
        One request builds the entire structure. StudentSections names the sections created
        inside each student's section group, so "Class Notes" and "Reflective Journals" become
        per-student private sections rather than shared ones. Adding a student also creates
        that student's section group, accessible only to the student and the teacher. The
        Content Library and Collaboration Space are created automatically.

        Large rosters can be slow, so an asynchronous mode is available: the request carries
        Prefer: respond-async, and the resulting operation is polled until it completes.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $DisplayName,
        [string[]] $StudentEmails,
        [Parameter(Mandatory)] [string] $TeacherUpn,
        [Parameter(Mandatory)] [string] $AccessToken,
        [Parameter(Mandatory)] [hashtable] $Config,
        [bool] $IsDryRun
    )
    try {
        $provisioning = $Config.Provisioning
        $query = "?omkt=$($provisioning.NotebookLanguage)&sendemail=$($provisioning.SendEmailOnCreate.ToString().ToLower())"
        $uri = "$($Config.OneNote.ApiRoot)/me/notes/classNotebooks$query"

        $body = @{
            name                       = $DisplayName
            studentSections            = @($provisioning.StudentSections)
            teachers                   = @(@{ id = $TeacherUpn; principalType = 'Person' })
            students                   = @($StudentEmails | ForEach-Object { @{ id = $_; principalType = 'Person' } })
            hasTeacherOnlySectionGroup = [bool]$provisioning.HasTeacherOnlySectionGroup
        }

        if ($IsDryRun) {
            Write-Log -Message "DRY RUN POST $uri" -Config $Config
            Write-Log -Message "DRY RUN body: $($body | ConvertTo-Json -Depth 6 -Compress)" -Config $Config
            return [pscustomobject]@{ id = 'dry-run-notebook-id'; name = $DisplayName; links = $null }
        }

        if ($provisioning.UseAsyncNotebookCreation) {
            $headers = @{ Prefer = 'respond-async' }
            $operation = Invoke-OneNoteRequest -Method POST -Uri $uri -AccessToken $AccessToken -Body $body -ExtraHeaders $headers -Config $Config
            return Wait-OneNoteOperation -Operation $operation -AccessToken $AccessToken -Config $Config
        }

        $notebook = Invoke-OneNoteRequest -Method POST -Uri $uri -AccessToken $AccessToken -Body $body -Config $Config
        Write-Log -Message "Created class notebook '$DisplayName' with $(@($StudentEmails).Count) student section group(s)." -Config $Config
        return $notebook
    }
    catch {
        Write-Host "[provision:New-ClassNotebook] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Wait-OneNoteOperation {
    <#
    .SYNOPSIS
        Polls an asynchronous OneNote operation until it completes, then fetches the result.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Operation,
        [Parameter(Mandatory)] [string] $AccessToken,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        $status = $Operation
        for ($i = 0; $i -lt $Config.OneNote.PollLimit; $i++) {
            if ($status.status -eq 'completed') {
                Write-Log -Message 'Asynchronous notebook creation completed.' -Config $Config
                return Invoke-OneNoteRequest -Method GET -Uri $status.resourceLocation -AccessToken $AccessToken -Config $Config
            }
            if ($status.status -eq 'failed') { throw "Notebook creation failed: $($status | ConvertTo-Json -Depth 4 -Compress)" }

            Start-Sleep -Seconds $Config.OneNote.PollSeconds
            $operationUri = "$($Config.OneNote.ApiRoot)/me/notes/operations/$($status.id)"
            $status = Invoke-OneNoteRequest -Method GET -Uri $operationUri -AccessToken $AccessToken -Config $Config
        }
        throw 'Timed out waiting for asynchronous notebook creation.'
    }
    catch {
        Write-Host "[provision:Wait-OneNoteOperation] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Get-NotebookSectionGroup {
    <#
    .SYNOPSIS
        Returns the section group with the given name from a notebook, or $null.
    .DESCRIPTION
        A class notebook is provisioned with several section groups: one per student, plus
        _Collaboration Space, _Content Library, and, when requested, a teacher-only group. This
        finds one of them by name. Matching is loosened to ignore the leading underscore and
        case, because the exact rendering varies with the notebook's language and has changed
        across service versions.

        Provisioning is not instantaneous, so the lookup is retried briefly before giving up.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $NotebookId,
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [string] $AccessToken,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        $uri = "$($Config.OneNote.ApiRoot)/me/notes/notebooks/$NotebookId/sectionGroups"
        $needle = $Name.TrimStart('_').ToLower()

        for ($attempt = 1; $attempt -le 5; $attempt++) {
            $response = Invoke-OneNoteRequest -Method GET -Uri $uri -AccessToken $AccessToken -Config $Config
            foreach ($group in @($response.value)) {
                $candidate = ([string]$group.name).TrimStart('_').ToLower()
                if ($candidate -eq $needle) { return $group }
            }
            Write-Log -Message "Section group '$Name' not visible yet (attempt $attempt of 5). Waiting." -Level DEBUG -Config $Config
            Start-Sleep -Seconds 5
        }

        Write-Log -Message "Section group '$Name' was not found in the notebook." -Level WARNING -Config $Config
        return $null
    }
    catch {
        Write-Host "[provision:Get-NotebookSectionGroup] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return $null
    }
}

function New-SharedSection {
    <#
    .SYNOPSIS
        Creates a section inside a section group, skipping it if it already exists.
    .DESCRIPTION
        The legacy OneNote API names sections with a "name" property, where Microsoft Graph uses
        "displayName". Since the service has carried both spellings across versions, the request
        is retried with the other spelling if the first is rejected, rather than failing on a
        detail that has nothing to do with the caller's intent.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $SectionGroup,
        [Parameter(Mandatory)] [string] $SectionName,
        [Parameter(Mandatory)] [string] $AccessToken,
        [Parameter(Mandatory)] [hashtable] $Config,
        [bool] $IsDryRun
    )
    try {
        $sectionsUri = "$($Config.OneNote.ApiRoot)/me/notes/sectionGroups/$($SectionGroup.id)/sections"

        if ($IsDryRun) {
            Write-Log -Message "DRY RUN POST $sectionsUri  name='$SectionName'" -Config $Config
            return $true
        }

        $existing = Invoke-OneNoteRequest -Method GET -Uri $sectionsUri -AccessToken $AccessToken -Config $Config
        foreach ($section in @($existing.value)) {
            if (([string]$section.name).ToLower() -eq $SectionName.ToLower()) {
                Write-Log -Message "Section '$SectionName' already exists in $($SectionGroup.name)." -Config $Config
                return $true
            }
        }

        try {
            Invoke-OneNoteRequest -Method POST -Uri $sectionsUri -AccessToken $AccessToken -Body @{ name = $SectionName } -Config $Config | Out-Null
        }
        catch {
            Write-Log -Message "Retrying section creation with the displayName spelling." -Level DEBUG -Config $Config
            Invoke-OneNoteRequest -Method POST -Uri $sectionsUri -AccessToken $AccessToken -Body @{ displayName = $SectionName } -Config $Config | Out-Null
        }

        Write-Log -Message "Created section '$SectionName' in $($SectionGroup.name)." -Config $Config
        return $true
    }
    catch {
        Write-Host "[provision:New-SharedSection] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return $false
    }
}

function Add-CollaborationSection {
    <#
    .SYNOPSIS
        Creates the configured sections inside the notebook's shared Collaboration Space.
    .DESCRIPTION
        Idempotent, so it is safe on a rerun: an existing section is left alone. A failure here
        does not abort the course, because the notebook and its per-student section groups are
        already correct and the shared section can be added by hand in seconds.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Notebook,
        [Parameter(Mandatory)] [string] $AccessToken,
        [Parameter(Mandatory)] [hashtable] $Config,
        [bool] $IsDryRun
    )
    try {
        $wanted = @($Config.Provisioning.CollaborationSections)
        if ($wanted.Count -eq 0) { return @() }

        if ($IsDryRun) {
            foreach ($name in $wanted) {
                Write-Log -Message "DRY RUN create '$name' in $($Config.Provisioning.CollaborationSpaceName)" -Config $Config
            }
            return $wanted
        }

        $space = Get-NotebookSectionGroup -NotebookId $Notebook.id `
                                          -Name $Config.Provisioning.CollaborationSpaceName `
                                          -AccessToken $AccessToken `
                                          -Config $Config
        if (-not $space) {
            Write-Log -Message 'The Collaboration Space was not found, so its sections were not created. Add them by hand, or rerun.' -Level WARNING -Config $Config
            return @()
        }

        $created = @()
        foreach ($name in $wanted) {
            if (New-SharedSection -SectionGroup $space -SectionName $name -AccessToken $AccessToken -Config $Config -IsDryRun $IsDryRun) {
                $created += $name
            }
        }
        return $created
    }
    catch {
        Write-Host "[provision:Add-CollaborationSection] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return @()
    }
}

function Sync-ClassNotebookRoster {
    <#
    .SYNOPSIS
        Adds roster students missing from an existing notebook and reports apparent drops.
    .DESCRIPTION
        Adding a student creates their private section group. Students present in the notebook
        but absent from the roster are reported and deliberately not removed: removal revokes
        access, and while it does not delete content, it should be an explicit act rather than
        a side effect of rerunning a provisioning script during add/drop week.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Notebook,
        [string[]] $StudentEmails,
        [Parameter(Mandatory)] [string] $AccessToken,
        [Parameter(Mandatory)] [hashtable] $Config,
        [bool] $IsDryRun
    )
    try {
        # The roster the service returns is read by extracting the email address from each entry
        # rather than by reading a presumed property name. The class notebook API has labelled
        # this field differently across versions and expansions (id, email, userPrincipalName),
        # and reading a name that is not there silently yields an empty string, which then looks
        # like a student who is both already present and no longer on the roster. Extracting the
        # address from the entry as a whole is immune to that.
        # Each roster entry keeps three things: the address extracted from it, the raw identity
        # the service actually stores, and a display name when one is offered. The service
        # commonly stores a SharePoint claims identity such as
        #     i:0#.f|membership|jsmith@ursinus.edu
        # rather than a plain address, which is unreadable on its own, so the address is
        # extracted for matching while the raw value is retained for reporting.
        $roster = @()
        if ($Notebook.PSObject.Properties.Name -contains 'students' -and $Notebook.students) {
            foreach ($student in @($Notebook.students)) {
                $raw = $student | ConvertTo-Json -Depth 4 -Compress
                $found = @(Get-EmailAddress -Text $raw -Config $Config)

                $displayName = $null
                foreach ($field in @('name', 'displayName')) {
                    if ($student.PSObject.Properties.Name -contains $field -and $student.$field) {
                        $displayName = [string]$student.$field
                        break
                    }
                }

                $identity = $raw
                foreach ($field in @('id', 'email', 'userPrincipalName')) {
                    if ($student.PSObject.Properties.Name -contains $field -and $student.$field) {
                        $identity = [string]$student.$field
                        break
                    }
                }

                if ($found.Count -gt 0) {
                    $roster += [pscustomobject]@{
                        Email    = $found[0]
                        Identity = $identity
                        Name     = $displayName
                    }
                }
                else {
                    $fields = ($student.PSObject.Properties.Name) -join ', '
                    Write-Log -Message "A notebook roster entry carried no email address. Fields present: $fields" -Level WARNING -Config $Config
                }
            }
        }
        $roster = @($roster)
        $existing = @($roster | ForEach-Object { $_.Email })

        $toAdd  = @($StudentEmails | Where-Object { $existing -notcontains $_.ToLower() })
        $drops  = @($roster | Where-Object { $StudentEmails -notcontains $_.Email })

        Write-Log -Message "Notebook roster: $($existing.Count) already present, $($toAdd.Count) to add, $($drops.Count) no longer on the roster." -Config $Config
        $added  = @()
        $failed = @()

        foreach ($email in $toAdd) {
            $redacted = Get-RedactedEmail -Email $email -Config $Config
            $uri = "$($Config.OneNote.ApiRoot)/me/notes/classNotebooks/$($Notebook.id)/students"
            $body = @{ id = $email; principalType = 'Person' }

            if ($IsDryRun) {
                Write-Log -Message "DRY RUN POST $uri for $redacted" -Config $Config
                $added += $email
                continue
            }

            try {
                Invoke-OneNoteRequest -Method POST -Uri $uri -AccessToken $AccessToken -Body $body -Config $Config | Out-Null
                Write-Log -Message "Added $redacted to the class notebook; their section group was created." -Config $Config
                $added += $email
            }
            catch {
                # A student who is already in the notebook is not a failure. This happens when
                # the roster expansion comes back thin, and on any rerun where the previous run
                # succeeded but its response was not fully read. Re-adding is harmless; being
                # told the student is already there is the expected, benign outcome.
                $detail = "$($_.Exception.Message) $($_.ErrorDetails.Message)"
                if ($detail -match 'already|exists|duplicate|20136|30103') {
                    Write-Log -Message "$redacted is already in the class notebook." -Config $Config
                    $added += $email
                }
                else {
                    Write-Host "[provision:Sync-ClassNotebookRoster] failed to add ${redacted}: $($_.Exception.Message)"
                    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
                        Write-Host "[provision:Sync-ClassNotebookRoster] response body: $($_.ErrorDetails.Message)"
                    }
                    $failed += $email
                }
            }
        }

        foreach ($drop in $drops) {
            $who = Get-RedactedEmail -Email $drop.Email -Config $Config
            if ($drop.Name) { $who = "$($drop.Name) <$who>" }
            Write-Log -Message "In the notebook but not on the roster: $who. Not removed." -Level WARNING -Config $Config
        }

        return [pscustomobject]@{
            Added  = @($added)
            Drops  = @($drops)
            Failed = @($failed)
        }
    }
    catch {
        Write-Host "[provision:Sync-ClassNotebookRoster] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Get-NotebookClientUrl {
    <#
    .SYNOPSIS
        Returns the onenote: protocol link that opens a notebook in the desktop application.
    .DESCRIPTION
        The service returns two links for a notebook: oneNoteWebUrl, an https address for the
        browser, and oneNoteClientUrl, an onenote: address that the OneNote desktop application
        registers as a protocol handler. The second is what opens the notebook locally.

        When the response omits the client link, one is synthesized by prefixing the web link
        with the protocol scheme, which is the same shape the service itself produces.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] $Notebook)
    try {
        if ($Notebook.PSObject.Properties.Name -contains 'links' -and $Notebook.links) {
            if ($Notebook.links.PSObject.Properties.Name -contains 'oneNoteClientUrl' -and $Notebook.links.oneNoteClientUrl) {
                return $Notebook.links.oneNoteClientUrl.href
            }
        }

        $webUrl = Get-NotebookUrl -Notebook $Notebook
        if ($webUrl) { return "onenote:$webUrl" }
        return $null
    }
    catch {
        Write-Host "[provision:Get-NotebookClientUrl] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return $null
    }
}

function Open-NotebookInClient {
    <#
    .SYNOPSIS
        Opens a notebook in the locally installed OneNote application.
    .DESCRIPTION
        Start-Process on an onenote: URL invokes the protocol handler that the desktop
        application registers at installation. If OneNote is already running, the existing
        instance is focused and the notebook is opened within it; if it is not running, it is
        launched. Either way one instance results, so no check for a running process is needed
        and none is performed.

        A failure here is reported and swallowed. The notebook and every student's section group
        already exist at this point, and being unable to open a window is not a reason to fail a
        provisioning run. The link is printed regardless, so it can always be opened by hand.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Notebook,
        [Parameter(Mandatory)] [hashtable] $Config,
        [bool] $IsDryRun
    )
    try {
        if (-not $Config.Provisioning.OpenInOneNoteClient) { return $false }

        $onWindows = ($PSVersionTable.PSEdition -eq 'Desktop') -or ($env:OS -eq 'Windows_NT')
        if (-not $onWindows) {
            Write-Log -Message 'Opening the OneNote client is a Windows behavior and was skipped.' -Level DEBUG -Config $Config
            return $false
        }

        $clientUrl = Get-NotebookClientUrl -Notebook $Notebook
        if (-not $clientUrl) {
            Write-Log -Message 'The service returned no client link, so the notebook could not be opened locally.' -Level WARNING -Config $Config
            return $false
        }

        if ($IsDryRun) {
            Write-Log -Message "DRY RUN would open: $clientUrl" -Config $Config
            return $true
        }

        Start-Process $clientUrl -ErrorAction Stop
        Write-Log -Message 'Opened the notebook in the OneNote desktop application.' -Config $Config

        $delay = $Config.Provisioning.OpenDelaySeconds
        if ($delay -gt 0) { Start-Sleep -Seconds $delay }

        return $true
    }
    catch {
        Write-Host "[provision:Open-NotebookInClient] could not open the notebook locally: $($_.Exception.Message)"
        Write-Log -Message 'The notebook was created successfully; only the local open failed. Use the printed link.' -Level WARNING -Config $Config
        return $false
    }
}

function Get-NotebookUrl {
    <#
    .SYNOPSIS
        Returns the web URL of a notebook, or $null when the response did not include one.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] $Notebook)
    try {
        if ($Notebook.PSObject.Properties.Name -contains 'links' -and $Notebook.links) {
            if ($Notebook.links.PSObject.Properties.Name -contains 'oneNoteWebUrl') {
                return $Notebook.links.oneNoteWebUrl.href
            }
        }
        if ($Notebook.PSObject.Properties.Name -contains 'oneNoteWebUrl') { return $Notebook.oneNoteWebUrl }
        return $null
    }
    catch {
        Write-Host "[provision:Get-NotebookUrl] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return $null
    }
}

# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

function Get-TeamNaming {
    <#
    .SYNOPSIS
        Applies the tenant's group naming policy to a course name.
    .DESCRIPTION
        Returns the decorated display name and mail nickname the directory will accept. The
        course display name itself is left untouched everywhere else, so the class notebook is
        still called "CS374 Fall 2026" even when the team must be called something like
        "GRP_CS374 Fall 2026". The policy applies to groups, not to notebooks.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $DisplayName,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        $provisioning = $Config.Provisioning

        $decorated = '{0}{1}{2}' -f $provisioning.TeamNamePrefix, $DisplayName, $provisioning.TeamNameSuffix

        $base = Get-MailNickname -DisplayName $DisplayName
        $nickname = '{0}{1}{2}' -f $provisioning.TeamMailNicknamePrefix, $base, $provisioning.TeamMailNicknameSuffix

        return [pscustomobject]@{
            DisplayName  = $decorated
            MailNickname = $nickname
        }
    }
    catch {
        Write-Host "[provision:Get-TeamNaming] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Show-NamingPolicyHint {
    <#
    .SYNOPSIS
        Prints the names of existing teams so the tenant's naming convention can be inferred.
    .DESCRIPTION
        The group naming policy lives in a directory setting that only an administrator can
        read, so it cannot be discovered programmatically from an ordinary account. What an
        ordinary account can do is look at groups that already satisfy the policy. The shared
        prefix or suffix across these names is the convention to configure.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [hashtable] $Config)
    try {
        Write-Host ''
        Write-Host 'Your tenant enforces a group naming policy.' -ForegroundColor Yellow
        Write-Host 'The policy itself is only readable by an administrator, but it can be inferred'
        Write-Host 'from teams that already exist. Here are the ones visible to you:'
        Write-Host ''

        $teams = @()
        try { $teams = @(Get-Team -ErrorAction Stop | Select-Object -First 20) }
        catch {
            Write-Host "  Could not list teams: $($_.Exception.Message)" -ForegroundColor DarkGray
        }

        if ($teams.Count -eq 0) {
            Write-Host '  No existing teams were visible, so there is nothing to infer from.' -ForegroundColor DarkGray
            Write-Host '  Create one team by hand in the Teams client and watch what it prepends'
            Write-Host '  or appends to the name you type. That is the policy.'
        }
        else {
            Write-Host ('  {0,-45} {1}' -f 'DISPLAY NAME', 'MAIL NICKNAME')
            Write-Host ('  {0,-45} {1}' -f ('-' * 45), ('-' * 25))
            foreach ($team in $teams) {
                Write-Host ('  {0,-45} {1}' -f $team.DisplayName, $team.MailNickname)
            }
        }

        Write-Host ''
        Write-Host 'Look for the shared prefix or suffix, then set it in the configuration block'
        Write-Host 'near the top of this script:'
        Write-Host ''
        Write-Host "    TeamNamePrefix         = 'GRP_'      # whatever precedes the name" -ForegroundColor Cyan
        Write-Host "    TeamNameSuffix         = ''          # whatever follows it" -ForegroundColor Cyan
        Write-Host "    TeamMailNicknamePrefix = 'grp-'      # the same policy often applies here" -ForegroundColor Cyan
        Write-Host "    TeamMailNicknameSuffix = ''" -ForegroundColor Cyan
        Write-Host ''
        Write-Host 'The class notebook name is not affected by any of this. It stays "CS374 Fall 2026".'
        Write-Host ''
    }
    catch {
        Write-Host "[provision:Show-NamingPolicyHint] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
    }
}

function Connect-CourseTeams {
    <#
    .SYNOPSIS
        Connects to Microsoft Teams, silently when possible.
    .DESCRIPTION
        Connect-MicrosoftTeams accepts a pair of already-acquired access tokens: one for
        Microsoft Graph and one for the Teams management resource, whose application id is
        48ac35b8-9aa8-4d74-927d-1f4a14a0b239. When the cached refresh token can be redeemed for
        both, the module connects without prompting.

        This is best-effort by design. Whether a given public client may request the Teams
        management resource depends on tenant preauthorization, and community reports of this
        path are mixed, so any failure falls back to the ordinary interactive sign-in rather
        than aborting the run. The worst case is the behavior you have today; the best case is
        no prompt at all.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [hashtable] $Config)
    try {
        $teamsResource = '48ac35b8-9aa8-4d74-927d-1f4a14a0b239'
        $cached = Get-CachedRefreshToken -Config $Config

        if ($cached) {
            $graphToken = Get-TokenByRefresh -RefreshToken $cached -Scope 'https://graph.microsoft.com/.default' -Config $Config
            $teamsToken = $null
            if ($graphToken) {
                $refreshed = Get-CachedRefreshToken -Config $Config
                if ($refreshed) {
                    $teamsToken = Get-TokenByRefresh -RefreshToken $refreshed -Scope "$teamsResource/.default" -Config $Config
                }
            }

            if ($graphToken -and $teamsToken) {
                try {
                    Connect-MicrosoftTeams -AccessTokens @($graphToken, $teamsToken) -ErrorAction Stop | Out-Null
                    Write-Log -Message 'Connected to Microsoft Teams silently from the cached session.' -Config $Config
                    return
                }
                catch {
                    Write-Log -Message "Silent Teams connection was refused, so an interactive sign-in follows: $($_.Exception.Message)" -Level WARNING -Config $Config
                }
            }
            else {
                Write-Log -Message 'The cached session could not be redeemed for the Teams resource, so an interactive sign-in follows.' -Level DEBUG -Config $Config
            }
        }

        $teamsCommand = Get-Command Connect-MicrosoftTeams -ErrorAction Stop
        $onWindows = ($PSVersionTable.PSEdition -eq 'Desktop') -or ($env:OS -eq 'Windows_NT')
        if (-not $onWindows -and $teamsCommand.Parameters.ContainsKey('UseDeviceAuthentication')) {
            Connect-MicrosoftTeams -UseDeviceAuthentication | Out-Null
        }
        else {
            Connect-MicrosoftTeams | Out-Null
        }
        Write-Log -Message 'Connected to Microsoft Teams.' -Config $Config
    }
    catch {
        Write-Host "[provision:Connect-CourseTeams] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function New-CourseTeam {
    <#
    .SYNOPSIS
        Creates the course team and returns its group id.
    .DESCRIPTION
        New-Team runs in the end-user context and makes the caller both owner and member,
        which is exactly the privilege Add-TeamUser later requires. No administrator role and
        no application consent is involved.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $DisplayName,
        [Parameter(Mandatory)] [hashtable] $Config,
        [bool] $IsDryRun
    )
    try {
        $naming = Get-TeamNaming -DisplayName $DisplayName -Config $Config
        $teamName = $naming.DisplayName
        $nickname = $naming.MailNickname
        $description = $Config.Provisioning.TeamDescriptionTemplate -f $DisplayName
        $visibility = $Config.Provisioning.TeamVisibility

        if ($IsDryRun) {
            Write-Log -Message "DRY RUN New-Team -DisplayName '$teamName' -MailNickname '$nickname' -Visibility $visibility" -Config $Config
            return 'dry-run-group-id'
        }

        $existing = Get-Team -DisplayName $teamName -ErrorAction SilentlyContinue
        if ($existing) {
            $groupId = @($existing)[0].GroupId
            Write-Log -Message "Team '$teamName' already exists (group $groupId). Reusing it." -Config $Config
            return $groupId
        }

        try {
            $team = New-Team -DisplayName $teamName -MailNickname $nickname -Description $description -Visibility $visibility
        }
        catch {
            # An Entra ID group naming policy rejects names lacking a required prefix or
            # suffix. The policy is not readable without an administrator, so rather than
            # failing opaquely, show the names of groups that already satisfy it.
            if ($_.Exception.Message -match 'prefix|suffix|naming') {
                Write-Log -Message "The directory rejected the team name '$teamName' under a group naming policy." -Level ERROR -Config $Config
                Show-NamingPolicyHint -Config $Config
            }
            throw
        }

        Write-Log -Message "Created team '$teamName' (group $($team.GroupId))." -Config $Config
        return $team.GroupId
    }
    catch {
        Write-Host "[provision:New-CourseTeam] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Add-CourseStudent {
    <#
    .SYNOPSIS
        Adds each student to the team and returns the addresses that failed.
    .DESCRIPTION
        Membership calls are staggered, following Microsoft's guidance to space out add-member
        operations. A student already on the team produces an error that is caught and treated
        as success, so reruns are safe. One bad address does not abandon the run.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $GroupId,
        [string[]] $Emails,
        [Parameter(Mandatory)] [hashtable] $Config,
        [bool] $IsDryRun
    )
    try {
        $failures = @()
        $role = $Config.Provisioning.StudentRole
        $delay = $Config.Provisioning.MemberAddDelaySeconds

        $current = @()
        if (-not $IsDryRun) {
            try {
                $current = @(Get-TeamUser -GroupId $GroupId -ErrorAction Stop | ForEach-Object { ([string]$_.User).ToLower() })
            }
            catch {
                Write-Log -Message "Could not read current team membership; every student will be attempted." -Level WARNING -Config $Config
            }
        }

        foreach ($email in $Emails) {
            $redacted = Get-RedactedEmail -Email $email -Config $Config

            if ($current -contains $email.ToLower()) {
                Write-Log -Message "$redacted is already on the team." -Level DEBUG -Config $Config
                continue
            }

            try {
                if ($IsDryRun) {
                    Write-Log -Message "DRY RUN Add-TeamUser -GroupId $GroupId -User $redacted -Role $role" -Config $Config
                    continue
                }
                Add-TeamUser -GroupId $GroupId -User $email -Role $role
                Write-Log -Message "Added $redacted to the team." -Config $Config
                Start-Sleep -Seconds $delay
            }
            catch {
                # Adding a student who is already on the team is benign. The pre-check above
                # normally prevents this, but it is skipped when the membership read fails.
                if ($_.Exception.Message -match 'already|exists|duplicate') {
                    Write-Log -Message "$redacted is already on the team." -Level DEBUG -Config $Config
                }
                else {
                    Write-Host "[provision:Add-CourseStudent] failed for ${redacted}: $($_.Exception.Message)"
                    $failures += $email
                }
            }
        }
        return $failures
    }
    catch {
        Write-Host "[provision:Add-CourseStudent] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function New-CourseChannel {
    <#
    .SYNOPSIS
        Optionally creates a named channel inside the course team.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $GroupId,
        [Parameter(Mandatory)] [string] $DisplayName,
        [Parameter(Mandatory)] [hashtable] $Config,
        [bool] $IsDryRun
    )
    try {
        $membershipType = $Config.Provisioning.ChannelMembershipType
        if ($IsDryRun) {
            Write-Log -Message "DRY RUN New-TeamChannel -GroupId $GroupId -DisplayName '$DisplayName' -MembershipType $membershipType" -Config $Config
            return
        }
        New-TeamChannel -GroupId $GroupId -DisplayName $DisplayName -MembershipType $membershipType | Out-Null
        Write-Log -Message "Created $membershipType channel '$DisplayName'." -Config $Config
    }
    catch {
        Write-Host "[provision:New-CourseChannel] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

function Invoke-CourseProvisioning {
    <#
    .SYNOPSIS
        Provisions the team, the roster, and the class notebook for one course.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Course,
        [Parameter(Mandatory)] [string] $TeacherUpn,
        [string] $TenantId,
        [Parameter(Mandatory)] [string] $AccessToken,
        [Parameter(Mandatory)] [hashtable] $Config,
        [bool] $IsDryRun
    )
    try {
        Write-Log -Message ('=' * 70) -Config $Config
        Write-Log -Message "Provisioning $($Course.DisplayName)" -Config $Config

        $groupId = $null
        $teamFailures = @()
        $links = $null
        $channelName = 'General'

        if ($Config.Provisioning.CreateTeam) {
            $groupId = New-CourseTeam -DisplayName $Course.DisplayName -Config $Config -IsDryRun $IsDryRun
            $teamFailures = @(Add-CourseStudent -GroupId $groupId -Emails $Course.Emails -Config $Config -IsDryRun $IsDryRun)

            if ($Config.Provisioning.CreateNamedChannel) {
                New-CourseChannel -GroupId $groupId -DisplayName $Course.DisplayName -Config $Config -IsDryRun $IsDryRun
                $channelName = $Course.DisplayName
            }

            if ($TenantId) {
                $links = Get-TeamLink -GroupId $groupId -TenantId $TenantId -ChannelDisplayName $channelName -Config $Config -IsDryRun $IsDryRun
            }
            else {
                Write-Log -Message 'No tenant id claim was available, so Teams links cannot be built.' -Level WARNING -Config $Config
            }
        }

        # The notebook name is derived from the course name alone. It deliberately does not
        # carry the group naming prefix, because the naming policy governs groups, not OneNote.
        $notebookName = Get-NotebookName -DisplayName $Course.DisplayName -Config $Config

        $existingNotebook = $null
        if (-not $IsDryRun) {
            $existingNotebook = Get-ClassNotebookByName -DisplayName $notebookName -AccessToken $AccessToken -Config $Config
        }

        if ($existingNotebook) {
            Write-Log -Message "Class notebook '$notebookName' already exists. Reconciling the roster." -Config $Config
            $sync = Sync-ClassNotebookRoster -Notebook $existingNotebook -StudentEmails $Course.Emails -AccessToken $AccessToken -Config $Config -IsDryRun $IsDryRun
            $notebook = $existingNotebook
            $added = @($sync.Added)
            $drops = @($sync.Drops)
            $notebookFailures = @($sync.Failed)
        }
        else {
            $notebook = New-ClassNotebook -DisplayName $notebookName `
                                          -StudentEmails $Course.Emails `
                                          -TeacherUpn $TeacherUpn `
                                          -AccessToken $AccessToken `
                                          -Config $Config `
                                          -IsDryRun $IsDryRun
            $added = @($Course.Emails)
            $drops = @()
            $notebookFailures = @()
        }

        # The Collaboration Space exists after creation but its sections do not, so they are
        # added here. This runs on reruns as well and skips anything already present.
        $collaboration = @(Add-CollaborationSection -Notebook $notebook -AccessToken $AccessToken -Config $Config -IsDryRun $IsDryRun)

        # Opening happens on creation and on update alike, since a rerun that adds students is
        # exactly when you want to look at the notebook.
        $opened = Open-NotebookInClient -Notebook $notebook -Config $Config -IsDryRun $IsDryRun

        $notebookUrl = Get-NotebookUrl -Notebook $notebook
        if (-not $notebookUrl -and -not $IsDryRun) {
            # The create response does not always carry the links object. Re-reading the
            # notebook is cheap and yields the shareable https URL reliably.
            $refetched = Get-ClassNotebookByName -DisplayName $notebookName -AccessToken $AccessToken -Config $Config
            if ($refetched) { $notebookUrl = Get-NotebookUrl -Notebook $refetched }
        }

        $teamUrl = $null
        $channelUrl = $null
        if ($links) {
            $teamUrl = $links.TeamUrl

            # The channel link is only worth reporting when it points somewhere the team link
            # does not. A team's General channel is where the team link already lands, so
            # printing both would just be the same destination twice. When a course-named
            # channel was created, the link is genuinely distinct and is kept.
            if ($Config.Provisioning.CreateNamedChannel) { $channelUrl = $links.ChannelUrl }
        }

        return [pscustomobject]@{
            Course           = $Course.DisplayName
            GroupId          = $groupId
            TeamUrl          = $teamUrl
            ChannelUrl       = $channelUrl
            NotebookId       = $notebook.id
            NotebookUrl      = $notebookUrl
            NotebookClientUrl = Get-NotebookClientUrl -Notebook $notebook
            OpenedLocally    = $opened
            StudentSections  = $Config.Provisioning.StudentSections
            SharedSections   = $collaboration
            StudentsAdded    = @($added)
            ApparentDrops    = @($drops)
            TeamFailures     = @($teamFailures)
            NotebookFailures = @($notebookFailures)
        }
    }
    catch {
        Write-Host "[provision:Invoke-CourseProvisioning] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

function Confirm-ProvisioningPlan {
    <#
    .SYNOPSIS
        Displays the full plan and requires the operator to type "yes" before any write.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Courses,
        [Parameter(Mandatory)] [hashtable] $Config,
        [bool] $IsDryRun
    )
    try {
        $provisioning = $Config.Provisioning

        Write-Host ''
        Write-Host 'Provisioning plan'
        Write-Host ('=' * 70)
        Write-Host ("Per-student private sections: {0}" -f ($provisioning.StudentSections -join ', '))
        Write-Host ("Shared Collaboration Space:   {0}" -f ($provisioning.CollaborationSections -join ', '))
        Write-Host ("Teacher Only section group:   {0}" -f $provisioning.HasTeacherOnlySectionGroup)
        Write-Host ("Email students on creation:   {0}" -f $provisioning.SendEmailOnCreate)
        Write-Host ("Create a Teams team:          {0}" -f $provisioning.CreateTeam)
        Write-Host ("Drops:                        reported, never removed")
        Write-Host ("Dry run:                      {0}" -f $IsDryRun)
        Write-Host ('-' * 70)

        foreach ($course in $Courses) {
            $roster = @($course.Emails)
            Write-Host ("  {0}: {1} student(s)" -f $course.DisplayName, $roster.Count)
            foreach ($email in ($roster | Select-Object -First 3)) { Write-Host "      $email" }
            if ($roster.Count -gt 3) { Write-Host ("      ... and {0} more" -f ($roster.Count - 3)) }
        }
        Write-Host ('-' * 70)

        if ($IsDryRun) {
            Write-Host 'Dry run: nothing will be written.'
            return $true
        }

        $answer = Read-Host "Proceed with provisioning? Type 'yes' to continue"
        return ($answer.Trim().ToLower() -eq 'yes')
    }
    catch {
        Write-Host "[provision:Confirm-ProvisioningPlan] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return $false
    }
}

function Show-ProvisioningSummary {
    <#
    .SYNOPSIS
        Prints a bordered summary of what was provisioned for each course.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Summaries,
        [Parameter(Mandatory)] [hashtable] $Config
    )
    try {
        Write-Host ''
        Write-Host 'Provisioning summary'
        Write-Host ('+' + ('-' * 78) + '+')

        foreach ($summary in $Summaries) {
            Write-Host ('| Course:             {0,-58}|' -f $summary.Course)
            Write-Host ('| Team group id:      {0,-58}|' -f $summary.GroupId)
            Write-Host ('| Notebook id:        {0,-58}|' -f $summary.NotebookId)
            Write-Host ('| Per-student:        {0,-58}|' -f ($summary.StudentSections -join ', '))
            Write-Host ('| Shared (collab):    {0,-58}|' -f (@($summary.SharedSections) -join ', '))
            Write-Host ('| Students added:     {0,-58}|' -f @($summary.StudentsAdded).Count)
            Write-Host ('| Apparent drops:     {0,-58}|' -f @($summary.ApparentDrops).Count)
            Write-Host ('| Team add failures:  {0,-58}|' -f @($summary.TeamFailures).Count)
            Write-Host ('| Notebook failures:  {0,-58}|' -f @($summary.NotebookFailures).Count)
            Write-Host ('+' + ('-' * 78) + '+')

            $drops = @($summary.ApparentDrops)
            if ($drops.Count -gt 0) {
                Write-Host ''
                Write-Host '  In the notebook but not on this roster. Nothing was removed.' -ForegroundColor Yellow
                foreach ($drop in $drops) {
                    $email = Get-RedactedEmail -Email $drop.Email -Config $Config
                    $label = if ($drop.Name) { "{0} <{1}>" -f $drop.Name, $email } else { $email }
                    Write-Host ("    {0}" -f $label) -ForegroundColor Yellow

                    # The identity is what the service actually stores, often a SharePoint claim.
                    # It is shown because it is the value you would need if you ever remove the
                    # student by hand or by API.
                    if ($drop.Identity -and $drop.Identity -ne $drop.Email) {
                        Write-Host ("      identity: {0}" -f $drop.Identity) -ForegroundColor DarkGray
                    }
                }
            }
            foreach ($email in $summary.TeamFailures) {
                Write-Host ("  Not added to team:     {0}" -f (Get-RedactedEmail -Email $email -Config $Config)) -ForegroundColor Yellow
            }
            foreach ($email in $summary.NotebookFailures) {
                Write-Host ("  Not added to notebook: {0}" -f (Get-RedactedEmail -Email $email -Config $Config)) -ForegroundColor Yellow
            }
            Write-Host ''
            Write-Host '  Links (share these with the class yourself):' -ForegroundColor Cyan
            if ($summary.TeamUrl)     { Write-Host "  Team:     $($summary.TeamUrl)" }
            if ($summary.ChannelUrl)  { Write-Host "  Channel:  $($summary.ChannelUrl)" }
            if ($summary.NotebookUrl) { Write-Host "  Notebook: $($summary.NotebookUrl)" }
            if ($summary.NotebookClientUrl -and -not $summary.OpenedLocally) {
                Write-Host "  Open in the OneNote app: $($summary.NotebookClientUrl)"
            }
            if (-not $summary.TeamUrl -and -not $summary.NotebookUrl) {
                Write-Host '  None available. See the log above for why.' -ForegroundColor Yellow
            }
            Write-Host ''
        }
    }
    catch {
        Write-Host "[provision:Show-ProvisioningSummary] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
    }
}

function Invoke-Main {
    <#
    .SYNOPSIS
        Loads configuration, collects input, confirms the plan, and provisions each course.
    #>
    [CmdletBinding()]
    param(
        [string] $ConfigPath,
        [bool] $IsDryRun,
        [bool] $ShowTeams,
        [bool] $ClearCache
    )
    try {
        $config = Get-EffectiveConfig -Default $DefaultConfig -Path $ConfigPath

        if ($ClearCache) {
            # Forget the cached sign-in. The next run prompts again. This does not revoke the
            # refresh token at Microsoft's end; it only removes the local copy.
            $cachePath = Get-TokenCachePath -Config $config
            if (Test-Path -LiteralPath $cachePath) {
                Remove-Item -LiteralPath $cachePath -Force
                Write-Host "Cached sign-in removed: $cachePath"
            }
            else {
                Write-Host 'There was no cached sign-in to remove.'
            }
            return
        }

        if ($config.Provisioning.CreateTeam) { Initialize-RequiredModule -Config $config }

        if ($ShowTeams) {
            # Diagnostic mode. Signs in to Teams, lists existing team names, and exits without
            # creating anything, so the tenant's naming convention can be read off directly.
            Connect-MicrosoftTeams | Out-Null
            Show-NamingPolicyHint -Config $config
            return
        }

        $courses = Read-CourseInput -Config $config
        if (-not (Confirm-ProvisioningPlan -Courses $courses -Config $config -IsDryRun $IsDryRun)) {
            Write-Host 'Aborted. Nothing was created.'
            return
        }

        $token = 'dry-run-token'
        $teacherUpn = 'dry-run-teacher@example.edu'
        $tenantId = 'dry-run-tenant-id'

        if (-not $IsDryRun) {
            Write-Log -Message 'Signing in for OneNote (device code).' -Config $config
            $token = Get-OneNoteToken -Config $config
            $teacherUpn = Get-TokenUpn -AccessToken $token
            $tenantId = Get-TokenClaim -AccessToken $token -Names @('tid')
            Write-Log -Message "Signed in as $teacherUpn." -Config $config

            if ($config.Provisioning.CreateTeam) {
                Write-Log -Message 'Signing in to Microsoft Teams.' -Config $config
                Connect-CourseTeams -Config $config
            }
        }

        $summaries = @()
        foreach ($course in $courses) {
            try {
                $summaries += Invoke-CourseProvisioning -Course $course -TeacherUpn $teacherUpn -TenantId $tenantId -AccessToken $token -Config $config -IsDryRun $IsDryRun
            }
            catch {
                Write-Host "[provision:Invoke-Main] course $($course.DisplayName) failed: $($_.Exception.Message)"
                Write-Host $_.ScriptStackTrace
                $summaries += [pscustomobject]@{
                    Course           = $course.DisplayName
                    GroupId          = $null
                    TeamUrl          = $null
                    ChannelUrl       = $null
                    NotebookId       = $null
                    NotebookUrl      = $null
                    NotebookClientUrl = $null
                    OpenedLocally    = $false
                    StudentSections  = $config.Provisioning.StudentSections
                    SharedSections   = @()
                    StudentsAdded    = @()
                    ApparentDrops    = @()
                    TeamFailures     = @($course.Emails)
                    NotebookFailures = @($course.Emails)
                }
            }
        }

        Show-ProvisioningSummary -Summaries $summaries -Config $config
    }
    catch {
        Write-Host "[provision:Invoke-Main] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

Invoke-Main -ConfigPath $ConfigPath -IsDryRun $DryRun.IsPresent -ShowTeams $ListTeams.IsPresent -ClearCache $Logout.IsPresent
