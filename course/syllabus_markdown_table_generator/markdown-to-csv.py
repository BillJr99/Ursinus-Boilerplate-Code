import sys
import csv
import frontmatter

def dictinsert(key, source, d, input):
    if source in input:
        if input[source] != False:
            d[key] = input[source]
        else:
            d[key] = ''
    else:
        d[key] = ''

def strip(x):
    return x.strip()
    
if len(sys.argv) < 2:
    print("Usage: <md filename>")
    sys.exit(-1)
    
fname = sys.argv[1]
syllabus = frontmatter.load(fname)
csvfile = open(fname + '.csv', 'w')
fieldnames = ["Week", "Day", "Title", "Link", "dtitle1", "dlink1", "dpoints1", "drubric1", "dtype1", "dtitle2", "dlink2", "dpoints2", "drubric2", "dtype2", "dtitle3", "dlink3", "dpoints3", "drubric3", "dtype3", "rtitle1", "rlink1", "rtitle2", "rlink2", "rtitle3", "rlink3", "rtitle4", "rlink4", "rtitle5", "rlink5"]
csvwriter = csv.DictWriter(csvfile, fieldnames=fieldnames)
csvwriter.writeheader()

for day in syllabus['schedule']:
    row = dict()
    
    dictinsert('Week', 'week', row, day)
    dictinsert('Day', 'date', row, day)
    dictinsert('Title', 'title', row, day)
    dictinsert('Link', 'link', row, day)
    
    if 'deliverables' in day:
        dcount = 1
        for deliverable in day['deliverables']:
            dictinsert('dtitle' + str(dcount), 'dtitle', row, deliverable)
            dictinsert('dlink' + str(dcount), 'dlink', row, deliverable)
            dictinsert('dpoints' + str(dcount), 'points', row, deliverable)
            dictinsert('dtype' + str(dcount), 'submission_types', row, deliverable)
            dictinsert('drubric' + str(dcount), 'rubricpath', row, deliverable)
            
            dcount += 1
            
            if dcount > 3:
                break
    else:
        for i in range(3):
            row['dtitle' + str(i+1)] = ''
            row['dlink' + str(i+1)] = ''
            row['dpoints' + str(i+1)] = ''
            row['drubric' + str(i+1)] = ''
            row['dtype' + str(i+1)] = ''
            
    if 'readings' in day:
        rcount = 1
        for reading in day['readings']:
            dictinsert('rtitle' + str(rcount), 'rtitle', row, reading)
            dictinsert('rlink' + str(rcount), 'rlink', row, reading)
            
            rcount += 1
            
            if rcount > 5:
                break
    else:
        for i in range(5):
            row['rtitle' + str(i+1)] = ''
            row['rlink' + str(i+1)] = ''
            
    csvwriter.writerow(row)
        
csvfile.close()
