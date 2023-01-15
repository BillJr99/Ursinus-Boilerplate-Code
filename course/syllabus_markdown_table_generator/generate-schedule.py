import sys
import csv

def strip(x):
    return x.strip()
    
if len(sys.argv) < 2:
    print("Usage: <csv filename>")
    sys.exit(-1)
    
fname = sys.argv[1]

csvfile = open(fname , 'r')

csvreader = csv.DictReader(csvfile,delimiter=',')
   
for row in csvreader:
    #print(row)  
    
    print("  - week: \"{}\"".format(row['Week']))
    print("    date: \"{}\"".format(row['Day']))
    print("    title: \"{}\"".format(row['Title']))
    if len(strip(row['Link'])) > 0:
        print("    link: \"{}\"".format(row['Link']))
    
    if len(strip(row['dtitle1'])) > 0:
        print("    deliverables:")
        print("      - dtitle: \"{}\"".format(row['dtitle1']))
        if len(strip(row['dlink1'])) > 0:
            print("        dlink: \"{}\"".format(row['dlink1']))
        else:
            print("        dlink: false")        
        print("        points: {}".format(row['dpoints1']))
        if len(strip(row['dtype1'])) > 0:
            print("        submission_types: \"{}\"".format(row['dtype1']))
        if len(strip(row['drubric1'])) > 0:
            print("        rubricpath: \"{}\"".format(row['drubric1']))
            
    if len(strip(row['dtitle2'])) > 0:
        print("      - dtitle: \"{}\"".format(row['dtitle2']))
        if len(strip(row['dlink2'])) > 0:
            print("        dlink: \"{}\"".format(row['dlink2']))
        else:
            print("        dlink: false")                
        print("        points: {}".format(row['dpoints2']))
        if len(strip(row['dtype2'])) > 0:
            print("        submission_types: \"{}\"".format(row['dtype2']))
        if len(strip(row['drubric2'])) > 0:
            print("        rubricpath: \"{}\"".format(row['drubric2']))            

    if len(strip(row['dtitle3'])) > 0:
        print("      - dtitle: \"{}\"".format(row['dtitle3']))
        if len(strip(row['dlink3'])) > 0:
            print("        dlink: \"{}\"".format(row['dlink3']))
        else:
            print("        dlink: false")                
        print("        points: {}".format(row['dpoints3']))
        if len(strip(row['dtype3'])) > 0:
            print("        submission_types: \"{}\"".format(row['dtype3'])) 
        if len(strip(row['drubric3'])) > 0:
            print("        rubricpath: \"{}\"".format(row['drubric3']))            

    if len(strip(row['rtitle1'])) > 0:
        print("    readings:")
        print("      - rtitle: \"{}\"".format(row['rtitle1']))
        if len(strip(row['rlink1'])) > 0:
            print("        rlink: \"{}\"".format(row['rlink1']))
        else:
            print("        rlink: false")

    if len(strip(row['rtitle2'])) > 0:
        print("      - rtitle: \"{}\"".format(row['rtitle2']))
        if len(strip(row['rlink2'])) > 0:
            print("        rlink: \"{}\"".format(row['rlink2']))
        else:
            print("        rlink: false")


    if len(strip(row['rtitle3'])) > 0:
        print("      - rtitle: \"{}\"".format(row['rtitle3']))
        if len(strip(row['rlink3'])) > 0:
            print("        rlink: \"{}\"".format(row['rlink3']))
        else:
            print("        rlink: false")
        
    if len(strip(row['rtitle4'])) > 0:
        print("      - rtitle: \"{}\"".format(row['rtitle4']))
        if len(strip(row['rlink4'])) > 0:
            print("        rlink: \"{}\"".format(row['rlink4']))
        else:
            print("        rlink: false")

    if len(strip(row['rtitle5'])) > 0:
        print("      - rtitle: \"{}\"".format(row['rtitle5']))
        if len(strip(row['rlink5'])) > 0:
            print("        rlink: \"{}\"".format(row['rlink5']))
        else:
            print("        rlink: false")
