import os
import sys
import argparse
from canvasapi import Canvas
import zipfile
import shutil

API_URL = "https://ursinus.instructure.com"  # Replace with your institution's Canvas URL
API_KEY = None

def get_arguments():
    parser = argparse.ArgumentParser(
        description="Download Canvas submissions into the current directory, skipping files "
                    "that already exist there or in any --existing-dir tree.")
    parser.add_argument("course_id", type=int)
    parser.add_argument("assignment_id", type=int)
    parser.add_argument("api_key")
    parser.add_argument("-e", "--existing-dir", action="append", default=[], metavar="PATH",
                        help="another directory tree to check for already-downloaded submissions "
                             "(searched recursively; may be repeated). New files are still saved "
                             "only under the current directory.")
    args = parser.parse_args()
    for d in args.existing_dir:
        if not os.path.isdir(d):
            print(f"Existing directory not found: {d}")
            sys.exit(1)
    return args.course_id, args.assignment_id, args.api_key, args.existing_dir

def sanitize_filename(name):
    return "".join(c if c.isalnum() or c in " ._-" else "_" for c in name)

def create_output_directory(course_id, assignment_id, assignment_name):
    dirname = f"course_{course_id}_assignment_{assignment_id}_{sanitize_filename(assignment_name)}"
    os.makedirs(dirname, exist_ok=True)
    return dirname

def save_assignment_prompt(assignment, output_dir):
    prompt_path = os.path.join(output_dir, "prompt.txt")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(f"Assignment Name: {assignment.name}\n")
        f.write(f"Due At: {assignment.due_at}\n")
        f.write(f"Description:\n{assignment.description or '[No description]'}\n")

def get_user_name(user_obj):
    if isinstance(user_obj, dict):
        return user_obj.get("name", "unknown_user")
    else:
        return getattr(user_obj, "name", "unknown_user")

def is_zip_file(filepath):
    try:
        with open(filepath, 'rb') as f:
            signature = f.read(4)
        return signature == b'PK\x03\x04'
    except Exception:
        return False

def index_existing(dirs):
    # Map each file name found anywhere under dirs to the set of sizes seen for it
    index = {}
    for d in dirs:
        for root, _, files in os.walk(d):
            for name in files:
                try:
                    size = os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
                index.setdefault(name, set()).add(size)
    return index

def reconcile_filename(user_name, attachment_filename, size, index):
    # Returns (filename, already_present). A name with a matching size is the same
    # submission; otherwise the first unused "Name", "Name 2", "Name 3", ... is new.
    base = sanitize_filename(user_name)
    file = sanitize_filename(attachment_filename)
    n = 1
    while True:
        candidate = f"{base}_{file}" if n == 1 else f"{base} {n}_{file}"
        if candidate not in index:
            return candidate, False
        if size is not None and size in index[candidate]:
            return candidate, True
        n += 1

def download_submissions(assignment, output_dir, existing_dirs=()):
    submissions = assignment.get_submissions(include=["user", "submission_history"])
    index = index_existing([output_dir] + list(existing_dirs))

    for submission in submissions:
        user = submission.user
        user_name = get_user_name(user)

        if hasattr(submission, "attachments") and submission.attachments:
            for attachment in submission.attachments:
                try:
                    size = getattr(attachment, "size", None)
                    filename, present = reconcile_filename(user_name, attachment.filename, size, index)
                    if present:
                        print(f"Skipping {filename} (already present)")
                        continue

                    filepath = os.path.join(output_dir, filename)
                    print(f"Downloading {filename}...")
                    attachment.download(filepath)
                    index.setdefault(filename, set()).add(os.path.getsize(filepath))

                    if is_zip_file(filepath):
                        extract_dir = os.path.join(output_dir, os.path.splitext(filename)[0])
                        os.makedirs(extract_dir, exist_ok=True)
                        print(f"Extracting ZIP file to {extract_dir}...")
                        with zipfile.ZipFile(filepath, 'r') as zip_ref:
                            zip_ref.extractall(extract_dir)
                except Exception as e:
                    print(f"Failed to handle attachment for {user_name}: {e}")
        else:
            print(f"No attachments found for {user_name}.")

def main():
    course_id, assignment_id, API_KEY, existing_dirs = get_arguments()
    canvas = Canvas(API_URL, API_KEY)

    try:
        course = canvas.get_course(course_id)
        assignment = course.get_assignment(assignment_id)
    except Exception as e:
        print(f"Error retrieving course or assignment: {e}")
        sys.exit(1)

    output_dir = create_output_directory(course_id, assignment_id, assignment.name)
    save_assignment_prompt(assignment, output_dir)
    download_submissions(assignment, output_dir, existing_dirs)
    print(f"Finished downloading submissions to '{output_dir}'.")

if __name__ == "__main__":
    main()
