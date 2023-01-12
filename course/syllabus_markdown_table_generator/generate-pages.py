import sys
import csv
import re

def write_file_line(f, text):
    f.write(text + "\r\n")

# basefolder: Activities, rootname: activity
def get_file_name_from_link(link, basefolder, rootname):
    fname = link.replace("./" + basefolder + "/", "").replace(" ", "").lower()
    fname = re.sub(r'\W+', '', fname) # remove non alphanumeric characters
    fname = rootname + "-" + fname + ".md"
    
    return fname

def get_deliverable_page_title(title):
    # remove everything after the first colon
    idx = title.find(":")
    if idx > -1:
        title = title[(idx+1):]
    
    if title.endswith(" Due"):
        title = title[:-4]
    
    title = title.strip() # remove leading/trailing spaces
    
    return title

def generate_activity_page(title, link, coursenum, coursetitle):
    fname = get_file_name_from_link(link, "Activities", "activity")
    f = open(fname, "w")
    
    write_file_line(f, "---")
    write_file_line(f, "layout: activity")
    write_file_line(f, "permalink: " + link.replace("./Activities", "/Activities"))
    write_file_line(f, "title: \"" + coursenum + ": " + coursetitle + " - " + title + "\"")
    write_file_line(f, "excerpt: \"" + coursenum + ": " + coursetitle + " - " + title + "\"")
    write_file_line(f, "")
    write_file_line(f, "info:")
    write_file_line(f, "  goals:")
    write_file_line(f, "    - xxx")
    write_file_line(f, "")
    write_file_line(f, "  models:")
    write_file_line(f, "    - model: |")
    write_file_line(f, "        xxx")
    write_file_line(f, "      title: xxx")
    write_file_line(f, "      questions:")
    write_file_line(f, "        - xxx")
    write_file_line(f, "")
    write_file_line(f, "  additional_reading:")
    write_file_line(f, "    - link: xxx")
    write_file_line(f, "      title: xxx")
    write_file_line(f, "")
    write_file_line(f, "  additional_practice:")
    write_file_line(f, "    - link: xxx")
    write_file_line(f, "      title: xxx")
    write_file_line(f, "")
    write_file_line(f, "tags:")
    write_file_line(f, "  - xxx")
    write_file_line(f, "")
    write_file_line(f, "---")
    write_file_line(f, "")
    
    f.close()
    
def generate_assignment_page(title, link, points, coursenum, coursetitle):
    fname = get_file_name_from_link(link, "Assignments", "assignment")
    f = open(fname, "w")
    
    write_file_line(f, "---")
    write_file_line(f, "layout: assignment")
    write_file_line(f, "permalink: " + link.replace("./Assignments", "/Assignments"))
    write_file_line(f, "title: \"" + coursenum + ": " + coursetitle + " - " + get_deliverable_page_title(title) + "\"")
    write_file_line(f, "excerpt: \"" + coursenum + ": " + coursetitle + " - " + get_deliverable_page_title(title) + "\"")
    write_file_line(f, "")
    write_file_line(f, "info:")
    write_file_line(f, "  coursenum: " + coursenum)
    write_file_line(f, "  points: " + points)
    write_file_line(f, "  goals:")
    write_file_line(f, "    - xxx")
    write_file_line(f, "")
    write_file_line(f, "  rubric:")
    write_file_line(f, "  - weight: 100")
    write_file_line(f, "    description: xxx")
    write_file_line(f, "    preemerging: xxx")
    write_file_line(f, "    beginning: xxx")
    write_file_line(f, "    progressing: xxx")
    write_file_line(f, "    proficient: xxx")
    write_file_line(f, "")
    write_file_line(f, "  readings:")
    write_file_line(f, "    - rlink: xxx")
    write_file_line(f, "      rtitle: xxx")
    write_file_line(f, "")
    write_file_line(f, "  questions:")
    write_file_line(f, "    - xxx")
    write_file_line(f, "")
    write_file_line(f, "tags:")
    write_file_line(f, "  - xxx")
    write_file_line(f, "")
    write_file_line(f, "---")
    write_file_line(f, "")
    
    f.close()

def generate_project_page(title, link, points, coursenum, coursetitle):
    fname = get_file_name_from_link(link, "Project", "project")
    f = open(fname, "w")
    
    write_file_line(f, "---")
    write_file_line(f, "layout: assignment")
    write_file_line(f, "permalink: " + link.replace("./Project", "/Project"))
    write_file_line(f, "title: \"" + coursenum + ": " + coursetitle + " - " + get_deliverable_page_title(title) + "\"")
    write_file_line(f, "excerpt: \"" + coursenum + ": " + coursetitle + " - " + get_deliverable_page_title(title) + "\"")
    write_file_line(f, "")
    write_file_line(f, "info:")
    write_file_line(f, "  coursenum: " + coursenum)
    write_file_line(f, "  points: " + points)
    write_file_line(f, "  goals:")
    write_file_line(f, "    - xxx")
    write_file_line(f, "")
    write_file_line(f, "  rubric:")
    write_file_line(f, "  - weight: 100")
    write_file_line(f, "    description: xxx")
    write_file_line(f, "    preemerging: xxx")
    write_file_line(f, "    beginning: xxx")
    write_file_line(f, "    progressing: xxx")
    write_file_line(f, "    proficient: xxx")
    write_file_line(f, "")
    write_file_line(f, "  readings:")
    write_file_line(f, "    - rlink: xxx")
    write_file_line(f, "      rtitle: xxx")
    write_file_line(f, "")
    write_file_line(f, "  questions:")
    write_file_line(f, "    - xxx")
    write_file_line(f, "")
    write_file_line(f, "tags:")
    write_file_line(f, "  - xxx")
    write_file_line(f, "")
    write_file_line(f, "---")
    write_file_line(f, "")
    
    f.close()   
    
def generate_lab_page(title, link, points, coursenum, coursetitle):
    fname = get_file_name_from_link(link, "Labs", "lab")
    f = open(fname, "w")
    
    write_file_line(f, "---")
    write_file_line(f, "layout: assignment")
    write_file_line(f, "permalink: " + link.replace("./Labs", "/Labs"))
    write_file_line(f, "title: \"" + coursenum + ": " + coursetitle + " - " + get_deliverable_page_title(title) + "\"")
    write_file_line(f, "excerpt: \"" + coursenum + ": " + coursetitle + " - " + get_deliverable_page_title(title) + "\"")
    write_file_line(f, "")
    write_file_line(f, "info:")
    write_file_line(f, "  coursenum: " + coursenum)
    write_file_line(f, "  points: " + points)
    write_file_line(f, "  goals:")
    write_file_line(f, "    - xxx")
    write_file_line(f, "")
    write_file_line(f, "  rubric:")
    write_file_line(f, "  - weight: 100")
    write_file_line(f, "    description: xxx")
    write_file_line(f, "    preemerging: xxx")
    write_file_line(f, "    beginning: xxx")
    write_file_line(f, "    progressing: xxx")
    write_file_line(f, "    proficient: xxx")
    write_file_line(f, "")
    write_file_line(f, "  readings:")
    write_file_line(f, "    - rlink: xxx")
    write_file_line(f, "      rtitle: xxx")
    write_file_line(f, "")
    write_file_line(f, "  questions:")
    write_file_line(f, "    - xxx")
    write_file_line(f, "")
    write_file_line(f, "tags:")
    write_file_line(f, "  - xxx")
    write_file_line(f, "")
    write_file_line(f, "---")
    write_file_line(f, "")
    
    f.close()  
    
def strip(x):
    return x.strip()
    
if len(sys.argv) < 4:
    print("Usage: <csv filename> <course number> \"<course title>\"")
    sys.exit(-1)
    
fname = sys.argv[1]
coursenum = sys.argv[2]
coursetitle = sys.argv[3]

csvfile = open(fname , 'r')

csvreader = csv.DictReader(csvfile,delimiter=',')
   
for row in csvreader:
    #print(row)  
    
    if 'Activities' in row['Link']:
        generate_activity_page(row['Title'], row['Link'], coursenum, coursetitle)
        
    for name, generator in [("Assignments", generate_assignment_page), ("Labs", generate_lab_page), ("Project", generate_project_page)]:
        for i in range(3):            
            if name in row['dlink' + str(i+1)] and "Due" in row['dtitle' + str(i+1)]:
                generator(row['dtitle' + str(i+1)], row['dlink' + str(i+1)], row['dpoints' + str(i+1)], coursenum, coursetitle)