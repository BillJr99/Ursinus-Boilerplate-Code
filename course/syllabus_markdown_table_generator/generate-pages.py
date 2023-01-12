import sys
import csv
import re
# basefolder: Activities, rootname: activity
def get_file_name_from_link(link, basefolder, rootname):
    fname = link.lower().replace("./" + basefolder + "/", "").replace(" ", "")
    fname = re.sub(r'\W+', '', fname) # remove non alphanumeric characters
    fname = rootname + "-" + fname + ".md"
    
    return fname

def generate_activity_page(title, link, coursenum, coursetitle):
    fname = get_file_name_from_link(link, "Activities", "activity")
    f = open(fname, "w")
    
    f.write("---")
    f.write("layout: activity")
    f.write("permalink: " + link.replace("./Activities", "/Activities"))
    f.write("title: \"" + coursenum + ": " + coursetitle + " - " + title + "\"")
    f.write("excerpt: \"" + coursenum + ": " + coursetitle + " - " + title + "\"")
    f.write("")
    f.write("info:")
    f.write("  goals:")
    f.write("    - xxx")
    f.write("")
    f.write("  models:")
    f.write("    - model: |")
    f.write("        xxx")
    f.write("      title: xxx")
    f.write("      questions:")
    f.write("        - xxx")
    f.write("")
    f.write("  additional_reading:")
    f.write("    - link: xxx")
    f.write("      title: xxx")
    f.write("")
    f.write("  additional_practice:")
    f.write("    - link: xxx")
    f.write("      title: xxx")
    f.write("")
    f.write("tags:")
    f.write("  - xxx")
    f.write("")
    f.write("---")
    f.write("")
    
    f.close()
    
def generate_assignment_page(title, link, points, coursenum, coursetitle):
    fname = get_file_name_from_link(link, "Assignments", "assignment")
    f = open(fname, "w")
    
    f.write("---")
    f.write("layout: assignment")
    f.write("permalink: " + link.replace("./Assignments", "/Assignments"))
    f.write("title: \"" + coursenum + ": " + coursetitle + " - " + title + "\"")
    f.write("excerpt: \"" + coursenum + ": " + coursetitle + " - " + title + "\"")
    f.write("")
    f.write("info:")
    f.write("  coursenum: " + coursenum)
    f.write("  points: " + points)
    f.write("  goals:")
    f.write("    - xxx")
    f.write("")
    f.write("  rubric:")
    f.write("  - weight: 100")
    f.write("    description: xxx")
    f.write("    preemerging: xxx")
    f.write("    beginning: xxx")
    f.write("    progressing: xxx")
    f.write("    proficient: xxx")
    f.write("")
    f.write("  readings:")
    f.write("    - rlink: xxx")
    f.write("      rtitle: xxx")
    f.write("")
    f.write("  questions:")
    f.write("    - xxx")
    f.write("")
    f.write("tags:")
    f.write("  - xxx")
    f.write("")
    f.write("---")
    f.write("")
    
    f.close()

def generate_project_page(title, link, points, coursenum, coursetitle):
    fname = get_file_name_from_link(link, "Project", "project")
    f = open(fname, "w")
    
    f.write("---")
    f.write("layout: assignment")
    f.write("permalink: " + link.replace("./Project", "/Project"))
    f.write("title: \"" + coursenum + ": " + coursetitle + " - " + title + "\"")
    f.write("excerpt: \"" + coursenum + ": " + coursetitle + " - " + title + "\"")
    f.write("")
    f.write("info:")
    f.write("  coursenum: " + coursenum)
    f.write("  points: " + points)
    f.write("  goals:")
    f.write("    - xxx")
    f.write("")
    f.write("  rubric:")
    f.write("  - weight: 100")
    f.write("    description: xxx")
    f.write("    preemerging: xxx")
    f.write("    beginning: xxx")
    f.write("    progressing: xxx")
    f.write("    proficient: xxx")
    f.write("")
    f.write("  readings:")
    f.write("    - rlink: xxx")
    f.write("      rtitle: xxx")
    f.write("")
    f.write("  questions:")
    f.write("    - xxx")
    f.write("")
    f.write("tags:")
    f.write("  - xxx")
    f.write("")
    f.write("---")
    f.write("")
    
    f.close()   
    
def generate_lab_page(title, link, points, coursenum, coursetitle):
    fname = get_file_name_from_link(link, "Labs", "lab")
    f = open(fname, "w")
    
    f.write("---")
    f.write("layout: assignment")
    f.write("permalink: " + link.replace("./Labs", "/Labs"))
    f.write("title: \"" + coursenum + ": " + coursetitle + " - " + title + "\"")
    f.write("excerpt: \"" + coursenum + ": " + coursetitle + " - " + title + "\"")
    f.write("")
    f.write("info:")
    f.write("  coursenum: " + coursenum)
    f.write("  points: " + points)
    f.write("  goals:")
    f.write("    - xxx")
    f.write("")
    f.write("  rubric:")
    f.write("  - weight: 100")
    f.write("    description: xxx")
    f.write("    preemerging: xxx")
    f.write("    beginning: xxx")
    f.write("    progressing: xxx")
    f.write("    proficient: xxx")
    f.write("")
    f.write("  readings:")
    f.write("    - rlink: xxx")
    f.write("      rtitle: xxx")
    f.write("")
    f.write("  questions:")
    f.write("    - xxx")
    f.write("")
    f.write("tags:")
    f.write("  - xxx")
    f.write("")
    f.write("---")
    f.write("")
    
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
        
    if 'Assignments' in row['dlink1']:
        generate_assignment_page(row['dtitle1'], row['dlink1'], row['dpoints1'], coursenum, coursetitle)

    if 'Assignments' in row['dlink2']:
        generate_assignment_page(row['dtitle2'], row['dlink2'], row['dpoints2'], coursenum, coursetitle)
        
    if 'Assignments' in row['dlink3']:
        generate_assignment_page(row['dtitle3'], row['dlink3'], row['dpoints3'], coursenum, coursetitle)        
        
    if 'Labs' in row['dlink1']:
        generate_lab_page(row['dtitle1'], row['dlink1'], row['dpoints1'], coursenum, coursetitle)

    if 'Labs' in row['dlink2']:
        generate_lab_page(row['dtitle2'], row['dlink2'], row['dpoints2'], coursenum, coursetitle)
        
    if 'Labs' in row['dlink3']:
        generate_lab_page(row['dtitle3'], row['dlink3'], row['dpoints3'], coursenum, coursetitle)     

    if 'Project' in row['dlink1']:
        generate_project_page(row['dtitle1'], row['dlink1'], row['dpoints1'], coursenum, coursetitle)

    if 'Project' in row['dlink2']:
        generate_project_page(row['dtitle2'], row['dlink2'], row['dpoints2'], coursenum, coursetitle)
        
    if 'Project' in row['dlink3']:
        generate_project_page(row['dtitle3'], row['dlink3'], row['dpoints3'], coursenum, coursetitle)           