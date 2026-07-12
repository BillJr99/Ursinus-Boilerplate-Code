<#
.SYNOPSIS
    Read-only probe. Determines whether Class Notebook automation is possible for this
    account, and if so, through which client identity.

.DESCRIPTION
    This script writes nothing. It creates no notebook, no team, and no permission. It
    performs a device-code sign-in and two GET requests, then reports what it found.

    Two open questions are answered:

      1. Can a Microsoft first-party public client obtain an access token whose audience
         is https://onenote.com/ ? This matters because the Class Notebook API lives on
         the legacy OneNote host rather than on Microsoft Graph, and a Graph-audience
         token will not work against it. Several well-known public client identities are
         tried in turn; the first that succeeds is reported.

      2. Is this account entitled to Class Notebooks? A GET against the classNotebooks
         endpoint answers this directly. A 200 means the feature is available. A 403 or a
         OneNote-specific error means it is not, and no amount of scripting will change
         that.

    The device-code flow is implemented against the identity platform REST endpoints with
    Invoke-RestMethod, so no modules are required at all. Nothing is installed.

.PARAMETER Tenant
    Tenant identifier or domain. Defaults to "organizations", which resolves the tenant
    from whichever work account signs in.

.EXAMPLE
    .\probe_classnotebook.ps1
#>

[CmdletBinding()]
param(
    [string] $Tenant = 'organizations'
)

Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
#
# Candidate public clients, tried in order. These are Microsoft first-party
# applications that exist in essentially every tenant and support the device-code flow
# without an app registration of our own. Which of them is preauthorized to request an
# onenote.com-audience token is precisely what this probe determines.
#
$Config = @{
    Authority = 'https://login.microsoftonline.com'
    Resource  = 'https://onenote.com'
    ApiRoot   = 'https://www.onenote.com/api/v1.0'
    Scopes    = 'https://onenote.com/Notes.ReadWrite offline_access'
    Clients   = @(
        @{ Name = 'Microsoft Graph Command Line Tools'; Id = '14d82eec-204b-4c2f-b7e8-296a70dab67e' },
        @{ Name = 'Microsoft Office';                   Id = 'd3590ed6-52b3-4102-aeff-aad2292ab01c' },
        @{ Name = 'Azure CLI';                          Id = '04b07795-8ddb-461a-bbee-02f9e1bf7b46' }
    )
    PollSeconds = 5
    PollLimit   = 60
}

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

function Get-DeviceCodeToken {
    <#
    .SYNOPSIS
        Runs the OAuth 2.0 device authorization grant for one client id and scope set.
    .DESCRIPTION
        Returns the access token on success, or $null when the client is not permitted to
        request the scope. A failure at the device-code initiation step means the client is
        not preauthorized for the requested resource, which is a finding rather than an
        error, so it is reported and swallowed rather than thrown.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $ClientId,
        [Parameter(Mandatory)] [string] $ClientName,
        [Parameter(Mandatory)] [hashtable] $Config
    )

    try {
        $deviceUri = "$($Config.Authority)/$Tenant/oauth2/v2.0/devicecode"
        $tokenUri  = "$($Config.Authority)/$Tenant/oauth2/v2.0/token"

        Write-Host ""
        Write-Host "Trying client: $ClientName"
        Write-Host "  Requesting scope: $($Config.Scopes)"

        try {
            $device = Invoke-RestMethod -Method POST -Uri $deviceUri -Body @{
                client_id = $ClientId
                scope     = $Config.Scopes
            } -ErrorAction Stop
        }
        catch {
            $detail = $_.ErrorDetails.Message
            Write-Host "  Result: this client cannot request an onenote.com token." -ForegroundColor Yellow
            if ($detail) { Write-Host "  Detail: $detail" -ForegroundColor DarkGray }
            return $null
        }

        Write-Host ""
        Write-Host $device.message -ForegroundColor Cyan
        Write-Host ""

        for ($i = 0; $i -lt $Config.PollLimit; $i++) {
            Start-Sleep -Seconds $Config.PollSeconds
            try {
                $token = Invoke-RestMethod -Method POST -Uri $tokenUri -Body @{
                    grant_type  = 'urn:ietf:params:oauth:grant-type:device_code'
                    client_id   = $ClientId
                    device_code = $device.device_code
                } -ErrorAction Stop

                Write-Host "  Result: token acquired." -ForegroundColor Green
                return $token.access_token
            }
            catch {
                $raw = $_.ErrorDetails.Message
                if ($raw -and ($raw -match 'authorization_pending')) { continue }
                if ($raw -and ($raw -match 'authorization_declined|expired_token')) {
                    Write-Host "  Result: sign-in was declined or the code expired." -ForegroundColor Yellow
                    return $null
                }
                Write-Host "  Result: token request failed." -ForegroundColor Yellow
                if ($raw) { Write-Host "  Detail: $raw" -ForegroundColor DarkGray }
                return $null
            }
        }

        Write-Host "  Result: timed out waiting for sign-in." -ForegroundColor Yellow
        return $null
    }
    catch {
        Write-Host "[probe:Get-DeviceCodeToken] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        return $null
    }
}

function Test-ClassNotebookEntitlement {
    <#
    .SYNOPSIS
        Calls GET /me/notes/classNotebooks and interprets the outcome.
    .DESCRIPTION
        A 200, whether or not any notebooks come back, establishes that the endpoint is
        reachable and the account is entitled. Any other outcome is reported verbatim,
        because the OneNote API returns its diagnostics in the response body and those
        details are what a support conversation would turn on.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $AccessToken,
        [Parameter(Mandatory)] [hashtable] $Config
    )

    try {
        $uri = "$($Config.ApiRoot)/me/notes/classNotebooks"
        Write-Host ""
        Write-Host "Calling GET $uri"

        $response = Invoke-RestMethod -Method GET -Uri $uri -Headers @{
            Authorization = "Bearer $AccessToken"
            Accept        = 'application/json'
        } -ErrorAction Stop

        $notebooks = @($response.value)
        Write-Host ""
        Write-Host "  Result: the classNotebooks endpoint responded successfully." -ForegroundColor Green
        Write-Host "  Existing class notebooks visible to you: $($notebooks.Count)"

        foreach ($notebook in ($notebooks | Select-Object -First 5)) {
            $sections = if ($notebook.PSObject.Properties.Name -contains 'studentSections') {
                $notebook.studentSections -join ', '
            } else { '(not returned)' }
            Write-Host "    - $($notebook.name)  [student sections: $sections]"
        }

        return $true
    }
    catch {
        $status = $null
        if ($_.Exception.PSObject.Properties.Name -contains 'Response' -and $_.Exception.Response) {
            $status = $_.Exception.Response.StatusCode.value__
        }

        Write-Host ""
        Write-Host "  Result: the classNotebooks endpoint rejected the request." -ForegroundColor Yellow
        if ($status) { Write-Host "  HTTP status: $status" }
        if ($_.ErrorDetails.Message) {
            Write-Host "  Response body:" -ForegroundColor DarkGray
            Write-Host "  $($_.ErrorDetails.Message)" -ForegroundColor DarkGray
        }
        Write-Host "  $($_.Exception.Message)" -ForegroundColor DarkGray
        return $false
    }
}

function Invoke-Probe {
    <#
    .SYNOPSIS
        Tries each candidate client until one yields a token, then tests entitlement.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [hashtable] $Config)

    try {
        Write-Host ""
        Write-Host "Class Notebook capability probe"
        Write-Host ("=" * 70)
        Write-Host "This script is read-only. It creates nothing and changes nothing."
        Write-Host "It answers two questions:"
        Write-Host "  1. Can a Microsoft public client get an onenote.com token for you?"
        Write-Host "  2. Is your account entitled to Class Notebooks?"
        Write-Host ("=" * 70)

        $token = $null
        $winningClient = $null

        foreach ($client in $Config.Clients) {
            $token = Get-DeviceCodeToken -ClientId $client.Id -ClientName $client.Name -Config $Config
            if ($token) {
                $winningClient = $client
                break
            }
        }

        Write-Host ""
        Write-Host ("=" * 70)
        Write-Host "Findings"
        Write-Host ("=" * 70)

        if (-not $token) {
            Write-Host "1. Token: NO candidate public client could obtain an onenote.com token." -ForegroundColor Red
            Write-Host "   This means Class Notebook automation needs an app registration whose"
            Write-Host "   permissions include the OneNote resource. That is a request to IT."
            Write-Host "2. Entitlement: not tested, because no token was available."
            return
        }

        Write-Host "1. Token: acquired through '$($winningClient.Name)'" -ForegroundColor Green
        Write-Host "   Client id: $($winningClient.Id)"
        Write-Host "   Put this client id in the provisioning script's configuration."

        $entitled = Test-ClassNotebookEntitlement -AccessToken $token -Config $Config

        Write-Host ""
        if ($entitled) {
            Write-Host "2. Entitlement: Class Notebooks are available to this account." -ForegroundColor Green
            Write-Host ""
            Write-Host "Both questions answered. The fully automated Class Notebook path is viable."
        }
        else {
            Write-Host "2. Entitlement: the endpoint rejected the call." -ForegroundColor Yellow
            Write-Host "   Send me the HTTP status and response body above and I will tell you"
            Write-Host "   whether this is a licensing problem, a consent problem, or a"
            Write-Host "   SharePoint site-permission problem, since the three look similar"
            Write-Host "   from the outside and have different remedies."
        }
    }
    catch {
        Write-Host "[probe:Invoke-Probe] $($_.Exception.Message)"
        Write-Host $_.ScriptStackTrace
        throw
    }
}

Invoke-Probe -Config $Config
