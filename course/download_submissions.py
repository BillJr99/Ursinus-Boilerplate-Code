import os
import sys
from canvasapi import Canvas
import zipfile
import shutil

API_URL = "https://ursinus.instructure.com"  # Replace with your institution's Canvas URL
API_KEY = None  

def get_arguments():
    if len(sys.argv) != 4:
        print("Usage: python download_submissions.py <course_id> <assignment_id> <api_key>")
        sys.exit(1)
    return int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]

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

def download_submissions(assignment, output_dir):
    submissions = assignment.get_submissions(include=["user", "submission_history"])

    for submission in submissions:
        user = submission.user
        user_name = get_user_name(user)

        if hasattr(submission, "attachments") and submission.attachments:
            for attachment in submission.attachments:
                try:
                    filename = f"{sanitize_filename(user_name)}_{sanitize_filename(attachment.filename)}"
                    filepath = os.path.join(output_dir, filename)
                    print(f"Downloading {filename}...")
                    attachment.download(filepath)

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
    course_id, assignment_id, API_KEY = get_arguments()
    canvas = Canvas(API_URL, API_KEY)
    
    try:
        course = canvas.get_course(course_id)
        assignment = course.get_assignment(assignment_id)
    except Exception as e:
        print(f"Error retrieving course or assignment: {e}")
        sys.exit(1)
    
    output_dir = create_output_directory(course_id, assignment_id, assignment.name)
    save_assignment_prompt(assignment, output_dir)
    download_submissions(assignment, output_dir)
    print(f"Finished downloading submissions to '{output_dir}'.")

if __name__ == "__main__":
    main()
