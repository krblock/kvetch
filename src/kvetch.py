#!/usr/bin/env python3

# Copyright 2025 Thinker Cats (thinkercats.com)
#
# Licensed under BSD 3-Clause License

import datetime
import io
import jenkins
import json
import os
from pathlib import Path
import sqlite3
import sys
import textwrap
import zlib

import scanlog

#
# Jenkins
#
# Go to https://<jenkins>/user/<username>/security/
# to create a token for logging in to jenkins. Store as ~/.ssh/jenkins-token.
#
def connect_jenkins():
    global server

    jenkins_url = 'https://<jenkins>'
    jenkins_username = os.getlogin()

    with open(Path.home().joinpath('.ssh/jenkins-token'), 'r') as file:
        jenkins_api_token = file.read()

    try:
        server = jenkins.Jenkins(jenkins_url,
                                        username=jenkins_username,
                                        password=jenkins_api_token)
    except jenkins.JenkinsException as e:
       raise Exception(f"Error connecting to Jenkins: {e}")

def get_job_num(real_job_info,field):
    if (real_job_info[field]):
        return real_job_info[field].get('number')
    else:
        return None

def get_jobs(view):
    jobs=[]
    view_jobs = server.get_jobs(view_name=view)
    for job in view_jobs:
# TBD: there is a bug here where I have to add "<NAME>/" to the name to
# retrieve the job_info. TBD.
        job_name = '<NAME>/'+job['name']
        jobs.append(job_name)
    return jobs

def get_job_info(job_name):
    job_info={}
    builds=[]
    real_job_info = server.get_job_info(job_name,
                                        fetch_all_builds=True)
    for build in real_job_info['builds']:
        builds.append(build['number'])

    job_info['name']                = job_name
    job_info['builds']              = builds
    job_info['lastBuild']           = get_job_num(real_job_info,'lastBuild')
    job_info['lastCompletedBuild']  = get_job_num(real_job_info,'lastCompletedBuild')
    job_info['lastFailedBuild']     = get_job_num(real_job_info,'lastFailedBuild')
    job_info['lastSuccessfulBuild'] = get_job_num(real_job_info,'lastSuccessfulBuild')
    return job_info

def get_job_infos(jobs_names,build_ids):
    job_infos=[]
    if (len(build_ids) == 0):
        for i in job_names:
            job_info=get_job_info(i)
            job_infos.append(job_info)
    else:
        job_info={}
        build_nums=[]
        
        for i in build_ids:
            if (i.isdigit()):
                build_nums.append(int(i))
            else:
                build_nums.clear()
                break
        
        for i in job_names:
            if (len(build_nums)==0):
                job_info=get_job_info(i)
                bnums=[]
                for i in build_ids:
                    if (i.isdigit()):
                        bnums.append(int(i))
                    else:
                        if (job_info[i]):
                            bnums.append(int(job_info[i]))
                job_info['builds'] = bnums
            else:
                job_info['name'] = i
                job_info['builds'] = build_nums
            job_infos.append(job_info)
    return job_infos

def get_build_info(job,build):
    real_build_info = server.get_build_info(job,build)

    build_info={}
    build_info['name']            = job
    build_info['number']          = build
    build_info['inProgress']      = real_build_info['inProgress']
    build_info['fullDisplayName'] = real_build_info['fullDisplayName']
    build_info['description']     = real_build_info['description']
    build_info['result']          = real_build_info['result']
    build_info['duration']        = real_build_info['duration']
    build_info['timestamp']       = real_build_info['timestamp']


    claim = next(
        (c for c in real_build_info['actions']
         if c.get('_class') == 'hudson.plugins.claim.ClaimBuildAction'),
        None)

    if (claim):
        build_info['claimedBy']       = claim['claimedBy']
        build_info['assignedBy']      = claim['assignedBy']
        build_info['claimDate']       = claim['claimDate']
        build_info['reason']          = claim['reason']

    return build_info

def get_build_console(job,build):
    return server.get_build_console_output(job,build)

def for_each_build(job_infos, build_pred, callback):
   for job_info in job_infos:
        try:
            job_name=job_info['name']
            builds = job_info['builds']
                    
            for build in builds:
                if (build_pred):
                    pred=build_pred(job_name,build)
                    if (pred is None):
                        break
                    if (pred):
                        continue
                
                build_info = get_build_info(job_name,build)

                callback(build_info)

        except jenkins.JenkinsException as e:
            print("%s has no jobs available" % job['name'])
            print(f"{e}")

def get_full_display_name(job_name, build_num):
    return job_name.replace("/", " » ", 1) + " #" + str(build_num)

#
# Org Chart
#
member_to_lead = {}
lead_to_members = {}

def process_team(team, parent_lead=None):
    lead = team.get("lead")
    if lead:
        lead_to_members.setdefault(lead, [])
        if parent_lead:
            member_to_lead[lead] = parent_lead
    for member in team.get("members", []):
        member_to_lead[member] = lead
        lead_to_members[lead].append(member)
    for subteam in team.get("teams", []):
        process_team(subteam, lead)

# Load org chart from corrected JSON file        
def init_org():
    with open("kvetch/org.json", "r") as f:
        org_chart = json.load(f)

        # Process the org chart
        process_team(org_chart)

# Interface functions
def get_lead_of(member_name):
    return member_to_lead.get(member_name, "Lead not found")

def get_members_of(lead_name):
    return lead_to_members.get(lead_name, [])

#
# Sqlite
#
def init_sqlite():
    db_path = 'tmp/kvetch-db'

    # Check if the database file already exists
    is_new_db = not os.path.exists(db_path)

    # Connect to the database
    global conn, cursor
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # During dev, we will frequently bump the version but once stable,
    # set back to the lowest unreleased numbed.
    schema_version=1

    # Only create tables if it's a new database
    if is_new_db:
        cursor.execute('CREATE TABLE schema (version INTEGER)')
        cursor.execute('INSERT INTO schema (version) VALUES (?)',
                       (str(schema_version)))

        cursor.execute('''
            CREATE TABLE logfiles (
                fullDisplayName TEXT PRIMARY KEY,
                contents BLOB
            )
        ''')

        cursor.execute('''
            CREATE TABLE builds (
                fullDisplayName TEXT PRIMARY KEY,
                description TEXT,
                result TEXT not NULL,
                duration INTEGER,
                timestamp INTEGER
            )
        ''')

        cursor.execute('''
            CREATE TABLE claims (
                fullDisplayName TEXT not NULL,
                claimedBy TEXT not NULL,
                assignedBy TEXT not NULL,
                claimDate INTEGER,
                reason TEXT
            )
        ''')

        conn.commit()

        print("Created Kvetch DB ver %d: %s" % (schema_version,db_path))
    else:
        cursor.execute('SELECT version FROM schema')
        row=cursor.fetchone()
        curr_version=row[0]
        if (curr_version != schema_version):
            if (curr_version < schema_version):
                print("Migrating Kvetch DB schema ver %d to %d"
                      % (curr_version, schema_version))
            else:
                print("Reseting Kvetch DB schema ver %d to %d"
                      % (curr_version, schema_version))
                
            cursor.execute("UPDATE schema set version = ?",
                           (str(schema_version)))
            conn.commit()

def db_build_exists(fullDisplayName):
    cursor.execute('''
        SELECT EXISTS(
            SELECT 1 FROM builds
            WHERE fullDisplayName = ?)
    ''', (fullDisplayName,))
    row = cursor.fetchone()
    return row[0] == 1

def db_add_build(build_info):
    fullDisplayName=build_info['fullDisplayName']
    description=build_info['description']
    result=build_info['result']
    duration=build_info['duration']
    timestamp=build_info['timestamp']
    cursor.execute('''
        INSERT INTO builds
        (fullDisplayName,description,result,duration,timestamp)
        VALUES (?,?,?,?,?)
    ''', (fullDisplayName,description,result,duration,timestamp))

    claimedBy=build_info.get('claimedBy')
    if (claimedBy):
        assignedBy=build_info['assignedBy']
        claimDate=build_info['claimDate']
        reason=build_info['reason']
        cursor.execute('''
            INSERT INTO claims
            (fullDisplayName,claimedBy,assignedBy,claimDate,reason)
            VALUES (?,?,?,?,?)
        ''', (fullDisplayName,claimedBy,assignedBy,claimDate,reason))

def db_get_build_info(job_name,build_num):
    fullDisplayName=get_full_display_name(job_name,build_num)

    cursor.execute('''
        SELECT fullDisplayName,description,result,duration,timestamp
        FROM builds
        WHERE fullDisplayName = ?
    ''', (fullDisplayName,))
    row=cursor.fetchone()
    if (row is None):
        return None
    build_info={}
    build_info['name']            = job_name
    build_info['number']          = build_num
    build_info['inProgress']      = False
    build_info['fullDisplayName'] = row[0]
    build_info['description']     = row[1]
    build_info['result']          = row[2]
    build_info['duration']        = row[3]
    build_info['timestamp']       = row[4]

    cursor.execute('''
        SELECT claimedBy,assignedBy,claimDate,reason
        FROM claims
        WHERE fullDisplayName = ?
    ''', (fullDisplayName,))
    row=cursor.fetchone()
    if row:
        build_info['claimedBy']   = row[0]
        build_info['assignedBy']  = row[1]
        build_info['claimDate']   = row[2]
        build_info['reason']      = row[3]
                       
    return build_info

def db_add_build_log(fullDisplayName,build_log):
    compressed_log = zlib.compress(build_log.encode('utf-8'))
    cursor.execute('''
        INSERT INTO logfiles
        (fullDisplayName,contents)
        VALUES (?,?)
    ''', (fullDisplayName,compressed_log))

def db_get_build_log(job_name,build_num):
    fullDisplayName=get_full_display_name(job_name,build_num)
    cursor.execute('''
        SELECT contents
        FROM logfiles
        WHERE fullDisplayName = ?
    ''', (fullDisplayName,))
    row=cursor.fetchone()
    build_log=zlib.decompress(row[0]).decode('utf-8')
    return build_log

def close_sqlite():
    conn.commit()
    conn.close()    

def db_for_each_build(job_infos, build_pred, callback):
   for job_info in job_infos:
        try:
            job_name=job_info['name']
            builds = job_info['builds']
                    
            for build in builds:
                if (build_pred):
                    pred=build_pred(job_name,build)
                    if (pred is None):
                        break
                    if (pred):
                        continue
                
                build_info = db_get_build_info(job_name,build)
                if (build_info is None):
                    continue

                callback(build_info)

        except jenkins.JenkinsException as e:
            print("%s has no jobs available" % job['name'])
            print(f"{e}")

def count_builds(job_infos):
    count = 0
    for job_info in job_infos:
        builds = job_info['builds']
        for build in builds:
           count+=1
    return count

#
# Common
#
def init():
    connect_jenkins()
    init_org()
    init_sqlite()

def finish():
    close_sqlite()

def print_build_json(build_info):
    pretty_json_string = json.dumps(build_info, indent=4)
    print(pretty_json_string)
    return False

#
# Skip if it already exists or is in progress
#
last_job=""
skip_count=0
def skip_build(job,build):
    global last_job, skip_count
    fullDisplayName=get_full_display_name(job,build)
    if db_build_exists(fullDisplayName):
        if (job == last_job):
            skip_count+=1
            if (skip_count > 3):
                return None # Abort
        else:
            last_job = job
            skip_count = 1
        return True # Skip
    skip_count=0
    return False # Do not skip

def record_build(build_info):
    print_build(build_info)
    if (build_info['inProgress']):
        return
    build_log = get_build_console(build_info['name'],build_info['number'])
    db_add_build(build_info)
    db_add_build_log(build_info['fullDisplayName'],build_log)
    return

def debug_print_job_names(job_names):
    for item in job_names:
        print(item)

def debug_print_jobs_builds(job_infos):
    for ji in job_infos:
        b=ji['builds']
        if (b):
            print("%s: %s" % (ji['name'],(",".join([str(num) for num in b]))))
        else:
            print("%s: empty" % ji['name'])

def print_build_internal(build_info,verbose):
    print("%-40s #%-4d" % (build_info['name'], build_info['number']), end='')
    if (verbose):
        print(" (%s, %s, %s)" %
              (build_info['description'],
               str(datetime.timedelta(seconds=int(build_info['duration'])//1000)),
               datetime.datetime.fromtimestamp(
                   int(build_info['timestamp'])//1000)),
              end='')
    if (build_info['inProgress']):
        print(" : RUNNING",end='')
    else:
        print(" : %s" % build_info['result'], end='')

    claimedBy = build_info.get('claimedBy')
    if (claimedBy):
        print(" claimed by %s" % claimedBy)
        reason=build_info['reason']
        if (reason):
            print(textwrap.indent(reason,'    '),end='')
        else:
            print(" is unclaimd",end='')

    print('')

def print_build(build_info):
    print_build_internal(build_info, True)
    
#
# print build status is an optimized version of print_build that avoids
# loading the build info for successful builds.
#
def print_jobs_status(job_infos):
    for ji in job_infos:
        name=ji['name']
        ls=ji['lastSuccessfulBuild']
        lc=ji['lastCompletedBuild']
        if (ls and lc):
            if (ls == lc):
                print("%-40s #%-4d : " % (name,lc),end='')
                print("SUCCESS")
            else:
                build_info = get_build_info(name,lc)
                print_build_internal(build_info, False)
        else:
            print("%-47s: UNKNOWN" % name)

def truncate_to_n_lines(s, n):
    lines = s.splitlines()
    return '\n'.join(lines[:n])

scan_log_limit = 0
def scan_log(buildlog):
    global scan_log_limit
    f=io.StringIO(buildlog)
    s=scanlog.scan_log(f)
    if (scan_log_limit > 0):
        print(truncate_to_n_lines(s['log'],scan_log_limit))
    else:
        print(s['log'])

enable_header = False
first_header = True
def print_header(name,num):
    global enable_header, first_header
    if (enable_header):
        if (not first_header):
            print("\n")
        first_header=False
        
        log_header=f"{name} #{num}"
        print(log_header)
        print('-'*len(log_header))
        print("")

        
def scan_log_callback(build_info):
    name=build_info['name']
    num=build_info['number']
    print_header(name,num)
    buildlog=get_build_console(name,num)
    scan_log(buildlog)

def db_scan_log_callback(build_info):
    name=build_info['name']
    num=build_info['number']
    print_header(name,num)
    buildlog=db_get_build_log(name,num)
    scan_log(buildlog)

def db_print_log_callback(build_info):
    name=build_info['name']
    num=build_info['number']
    print_header(name,num)
    buildlog=db_get_build_log(name,num)
    print(buildlog)

#
# Main Program
#

if __name__ == "__main__":
    import getopt

    opts,args = getopt.getopt(sys.argv[1:], 'v:j:b:adflnqrs')

    if len(args) > 0:
        print("Usage: %s" % sys.argv[0])
        sys.exit(1)

    init()

    view_name=None
    job_names=[]
    build_ids=[]
    
    for o, a in opts:
        if o == "-v":
            view_name = a
        elif o == "-j":
            job_names.append(a)
        elif o == "-b":
            build_ids.append(a)

    opts = dict(opts)

    if (view_name):
        job_names.extend(get_jobs(view_name))

    job_infos = get_job_infos(job_names,build_ids)

    #
    # These options only pull data from Jenkins
    #
    if '-s' in opts:
        if (len(build_ids)>0):
            print("ERROR: build ids not compatible with status")
            sys.exit(1)
        print_jobs_status(job_infos)
        sys.exit(0)
    elif '-a' in opts:
        for_each_build(job_infos, None, print_build_json)
        sys.exit(0)
    elif '-q' in opts:
        for_each_build(job_infos, None, print_build)
        sys.exit(0)
    elif '-r' in opts:
        # This is for triage at end of Job in Jenkins, no DB involved
        for_each_build(job_infos, None, scan_log_callback)
        sys.exit(0)

    #
    # Populate new data into DB from Jenkins unless specifically suspended
    #
    if (not '-n' in opts):
        for_each_build(job_infos, skip_build, record_build)

    #
    # These options only pull data from the DB
    #
    if (count_builds(job_infos) > 1):
        enable_header = True
        scan_log_limit = 10

    if '-d' in opts:
        db_for_each_build(job_infos,None,print_build)
        sys.exit(0)
    elif '-l' in opts:
        db_for_each_build(job_infos,None,db_print_log_callback)
        sys.exit(0)
    elif '-f' in opts:
        db_for_each_build(job_infos,None,db_scan_log_callback)
        sys.exit(0)
        
    if '-t' in opts:
        print("Trigger emails")

    if '-r' in opts:
        print("Generate reports")

    finish()
    sys.exit(0)

#
# Unit tests run with: python3 -m unittest <filename.py>
#
import unittest

class MyTestCase(unittest.TestCase):
    def test_jenkins(self):
        connect_jenkins()
        user = server.get_whoami()
        version = server.get_version()
        self.assertEqual(os.getlogin(),user['id'])
        self.assertEqual('2.516.1',version)


    def test_org(self):
        init_org()
        self.assertEqual('waltce',get_lead_of("garyv"))
        m=get_members_of("dsmith")
        self.assertEqual('coleenp',m[0])
        self.assertEqual('judyw',m[1])
        self.assertEqual('prem',m[2])
        self.assertEqual(3,len(m))
        
