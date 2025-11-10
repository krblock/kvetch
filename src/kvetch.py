#!/usr/bin/env python3

# Copyright 2025 Thinker Cats, Inc
#
# Licensed under BSD 3-Clause License

import datetime
from email.message import EmailMessage
import importlib
import io
import jenkins
import json
import os
from pathlib import Path
import re
import smtplib
import sqlite3
import sys
import textwrap
import zlib

#
# Jenkins
#
# Go to <jenkins_url>/user/<username>/security/
# to create a token for logging in to jenkins. Record location in
# kvetch.json config: jenkins_auth.
#
jenkins_url=None
jenkins_auth=None
def connect_jenkins():
    global server, jenkins_url

    jenkins_username = os.getlogin()

    with open(os.path.expanduser(jenkins_auth), 'r') as file:
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


def extract_job_component(url):
    """
    Extracts the component between two 'job/' segments in a Jenkins-style URL.
    """
    match = re.search(r'/job/([^/]+)/job/', url)
    if match:
        return match.group(1)
    return None

def get_jobs(view):
    jobs=[]
    view_jobs = server.get_jobs(view_name=view)

    for job in view_jobs:
        job_name = job['name']

# TBD: there is a bug here where the name given is missing the project
# prefix. We have implemented a workaround to get the prefix out of the URL.
# It is not clear how robust this is
        job_component = extract_job_component(job['url'])
        if (job_component):
            job_name=job_component+'/'+job_name

        jobs.append(job_name)
    return jobs

def get_job_info(job_name):
    job_info={}
    builds=[]
    real_job_info = server.get_job_info(job_name,
                                        fetch_all_builds=True)
    for build in real_job_info['builds']:
        builds.append(build['number'])

#    Use for for debug information
#    job_info['json']                = real_job_info
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
                        if (job_info.get(i)):
                            bnums.append(int(job_info[i]))
                        else:
                            if (not i in job_info):
                                raise RuntimeError(f"Unrecognized build {i}")

                job_info['builds'] = bnums
            else:
                job_info=get_job_info(i)
                job_info['builds'] = build_nums
                
            job_infos.append(job_info)
    return job_infos

def get_build_info(job,build):
    real_build_info = server.get_build_info(job,build)

    build_info={}
#    Use for for debug information
#    build_info['json']            = real_build_info
    build_info['name']            = job
    build_info['number']          = build
    build_info['inProgress']      = real_build_info['inProgress']
    build_info['fullDisplayName'] = real_build_info['fullDisplayName']
    build_info['description']     = real_build_info['description']
    build_info['result']          = real_build_info['result']
    build_info['duration']        = real_build_info['duration']
    build_info['timestamp']       = real_build_info['timestamp']
    build_info['url']             = real_build_info['url']

    change_set=[]
    real_changeSets = real_build_info.get('changeSets')
    if (real_changeSets):
        for real_changeSet in real_changeSets:
            for real_item in real_changeSet['items']:
                item={}
                item['authorEmail'] = real_item['authorEmail']
                item['comment'] = real_item['comment']
                item['affectedPaths'] = real_item['affectedPaths']
                item['commitId'] = real_item['commitId']
                change_set.append(item)

    build_info['changeSets'] = change_set

    claim = next(
        (c for c in real_build_info['actions']
         if c.get('_class') == 'hudson.plugins.claim.ClaimBuildAction'),
        None)

    if (claim):
        claim_infos=[]
        claim_info={}
        claim_info['claimedBy']       = claim['claimedBy']
        claim_info['assignedBy']      = claim['assignedBy']
        claim_info['claimDate']       = claim['claimDate']
        claim_info['reason']          = claim['reason']
        claim_infos.append(claim_info)
        build_info['claims']=claim_infos
    else:
        build_info['claims']=[]

    return build_info

def get_build_console(job,build):
    return server.get_build_console_output(job,build)

def for_each_build(job_infos, build_pred, callback,f):
    ret = False # Indicates if callback called
    for job_info in job_infos:
        try:
            job_name=job_info['name']
            builds = job_info['builds']
                    
            for build in builds:
                build_info = get_build_info(job_name,build)

                if (build_pred):
                    pred=build_pred(job_info,build_info)
                    if (pred is None):
                        break
                    if (pred):
                        continue
                
                callback(f,job_info,build_info)
                ret=True

        except jenkins.JenkinsException as e:
            print("%s has no jobs available" % job['name'])
            print(f"{e}")
    return ret

def get_full_display_name(job_name, build_num):
    return job_name.replace("/", " » ", 1) + " #" + str(build_num)

def get_developers(build_info):
    developers=set()
    for c in build_info['changeSets']:
        developers.add(c['authorEmail'])
    return developers

# Org Chart

member_to_lead = {}
lead_to_members = {}
member_to_email = {}

def get_username(user):
    username=user["username"]
    email=user["email"]
    member_to_email[username]=email
    return username

def process_team(team, parent_lead=None):
    lead = get_username(team.get("lead"))
    if lead:
        lead_to_members.setdefault(lead, [])
        if parent_lead:
            member_to_lead[lead] = parent_lead
    for member in team.get("members", []):
        member_name = get_username(member)
        member_to_lead[member_name] = lead
        lead_to_members[lead].append(member_name)
    for subteam in team.get("teams", []):
        process_team(subteam,lead)

# Load org chart from corrected JSON file
def init_org(org_file):
    with open(org_file, "r") as f:
        org_chart = json.load(f)

        # Process the org chart
        process_team(org_chart)

# Interface functions
def get_lead_of(member_name):
    return member_to_lead.get(member_name, "Lead not found")

def get_members_of(lead_name):
    return lead_to_members.get(lead_name, [])

def get_email_of(username):
    return member_to_email[username]

#
# Sqlite
#
db_path = None
def init_sqlite():
    global db_path

    # Check if the database file already exists
    is_new_db = not os.path.exists(db_path)
    if is_new_db:
        parent_dir = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent_dir, exist_ok=True)

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
            CREATE TABLE kvetch (
                jobName         TEXT PRIMARY KEY,
                target          TEXT,
                build           INTEGER,
                timestamp       INTEGER,
                level           INTEGER
            )
        ''')

        cursor.execute('''
            CREATE TABLE builds (
                fullDisplayName TEXT PRIMARY KEY,
                description TEXT,
                result TEXT not NULL,
                duration INTEGER,
                timestamp INTEGER,
                url TEXT not NULL,
                changeSets TEXT,
                claims TEXT
            )
        ''')

#
# JSON fields
#
# claims are a list of clams:
#     claimedBy TEXT not NULL,
#     assignedBy TEXT not NULL,
#     claimDate INTEGER,
#     reason TEXT
#
# changeSets are a list of changes:
#     commitId       TEXT not NULL,
#     authorEmail    TEXT not NULL,
#     comment        TEXT,
#     affectedPaths  list of TEXT,
#

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

def db_build_exists(job_info,build_info):
    fullDisplayName=build_info['fullDisplayName']
    cursor.execute('''
        SELECT claims FROM builds
        WHERE fullDisplayName = ?
    ''', (fullDisplayName,))
    row = cursor.fetchone()
    if (row):
        claims_str = json.dumps(build_info['claims'])
        if (row[0] != claims_str):
            cursor.execute('''
                UPDATE builds set claims = ?
                WHERE fullDisplayName = ?
            ''', (claims_str,fullDisplayName))
        return True
    else:
        return False

def db_add_build(build_info):
    fullDisplayName=build_info['fullDisplayName']
    description=build_info['description']
    result=build_info['result']
    duration=build_info['duration']
    timestamp=build_info['timestamp']
    url=build_info['url']

    changeSets_str = json.dumps(build_info['changeSets'])
    claims_str = json.dumps(build_info['claims'])

    cursor.execute('''
        INSERT INTO builds
        (fullDisplayName,description,result,duration,timestamp,url,
         changeSets,claims)
        VALUES (?,?,?,?,?,?,?,?)
    ''', (fullDisplayName,description,result,duration,timestamp,url,
          changeSets_str,claims_str))

def db_get_build_info(job_name,build_num):
    fullDisplayName=get_full_display_name(job_name,build_num)

    cursor.execute('''
        SELECT fullDisplayName,description,result,duration,timestamp,url,
               changeSets,claims
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
    build_info['url']             = row[5]
    build_info['changeSets']      = json.loads(row[6])
    build_info['claims']          = json.loads(row[7])

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

def db_get_kvetch_info(job_name):
    cursor.execute('''
        SELECT jobName, target, build, timestamp, level
        FROM kvetch
        WHERE jobName = ?
    ''', (job_name,))
    row=cursor.fetchone()
    if (not row):
        return None
    else:
        kvetch_info = {}
        kvetch_info['jobName']   = row[0]
        kvetch_info['target']    = row[1]
        kvetch_info['build']     = row[2]
        kvetch_info['timestamp'] = row[3]
        kvetch_info['level']     = row[4]
        return kvetch_info

def db_set_kvetch_info(kvetch_info):
    cursor.execute('''
        INSERT INTO kvetch (jobName, target, build, timestamp, level)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(jobName) DO UPDATE SET
            target    = excluded.target,
            build     = excluded.build,
            timestamp = excluded.timestamp,
            level     = excluded.level
    ''', (kvetch_info['jobName'],
          kvetch_info['target'],
          kvetch_info['build'],
          kvetch_info['timestamp'],
          kvetch_info['level']))
    conn.commit()

def commit_sqlite():
    conn.commit()

def close_sqlite():
    conn.close()    

def db_for_each_build(job_infos, build_pred, callback,f):
   for job_info in job_infos:
        try:
            job_name=job_info['name']
            builds = job_info['builds']
                    
            for build in builds:
                build_info = db_get_build_info(job_name,build)
                if (build_info is None):
                    continue

                if (build_pred):
                    pred=build_pred(build_info)
                    if (pred is None):
                        break
                    if (pred):
                        continue
                
                callback(f,job_info,build_info)

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
# Config
#
import os
import json

def find_and_load_json_config(filename="kvetch.json", search_paths=None):
    """Searches for a JSON config file in a list of directories and loads
    its contents.  Relative paths are resolved based on the script's
    location.

    Parameters:
    - filename (str): Name of the JSON file to search for.
    - search_paths (list): Directories to search. If not, use defaults.

    Returns:
    - dict: Parsed JSON content if found and valid.
    - None: If file not found or invalid JSON.

    """
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if (search_paths is None):
        search_paths = [
            ".",                             # script directory
            "./config",                      # ./config relative to script
            "./kvetch",                      # ./config relative to script
            os.path.expanduser("~/.kvetch")  # absolute path
        ]

    # Default to script directory if no paths provided
    if len(search_paths) == 0:
        resolved_paths = [ "." ]
    else:
        # Resolve all paths relative to the script's location
        resolved_paths = [os.path.abspath(os.path.join(script_dir, path))
                          for path in search_paths]

    for path in resolved_paths:
        full_path = os.path.join(path, filename)
        if os.path.isfile(full_path):
            try:
                with open(full_path, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON in {full_path}: {e}")
                return None

    print(f"{filename} not found in any of the specified paths: {resolved_paths}")
    return None

#
# Send an email
#
from_email=None
smtp_server=None
smtp_port=None

def send_email(to_email, cc_email, subject, body):
    global from_email, smtp_server, smtp_port

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    if (cc_email):
        msg['Cc'] = cc_email

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.send_message(msg)
        print("✅ Email sent successfully.")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

#
# Load user defined function
#
def load_func_from_file(file_path, function_name):
    """
    Loads a function from a Python file given its path and function name.

    Parameters:
    - file_path (str): Path to the .py file.
    - function_name (str): Name of the function to load.

    Returns:
    - Callable function object, or None if not found.
    """
    module_name = os.path.splitext(os.path.basename(file_path))[0]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, function_name, None)
    return None

#
# Common
#
def init(org_path):
    connect_jenkins()
    init_org(org_path)
    init_sqlite()

def finish():
    close_sqlite()

def print_json(f,dict):
    pretty_json_string = json.dumps(dict, indent=4)
    print(pretty_json_string,file=f)
    print("",file=f)

def print_build_json(f,job_info,build_info):
    pretty_json_string = json.dumps(job_info, indent=4)
    print(pretty_json_string,file=f)
    print("",file=f)

    pretty_json_string = json.dumps(build_info, indent=4)
    print(pretty_json_string,file=f)
    return False

def get_claim_info(build_info):
    claim_infos = build_info['claims']
    if (claim_infos and len(claim_infos)>0):
        return claim_infos[0]
    else:
        return None

def get_claimedBy(build_info):
    claim_info = get_claim_info(build_info)
    if (claim_info):
        return claim_info['claimedBy']
    else:
        return None

#
# Skip if it already exists or is in progress
#
last_job=""
skip_count=0
def skip_build(job_info,build_info):
    global last_job, skip_count
    if db_build_exists(job_info,build_info):
        if (job_info['name'] == last_job):
            skip_count+=1
            if (skip_count > 3):
                return None # Abort
        else:
            last_job = job_info['name']
            skip_count = 1
        return True # Skip
    skip_count=0
    return False # Do not skip

first_record=True
def record_build(f,job_info,build_info):
    global first_record
    if (first_record):
        print("Populating New Builds ...")
        first_record=False

    print_build_internal(f,job_info,build_info,False)
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

def time_elapsed(timestamp):
    now = datetime.datetime.now()
    elapsed = now - datetime.datetime.fromtimestamp(timestamp//1000)

    return elapsed

def time_elapsed_str(elapsed):
    days = elapsed.days
    seconds = elapsed.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    elif minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    elif secs > 0 or not parts:
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")

    return ", ".join(parts) + " ago"

def elapsed_failure_time(firstFailure,job_info,build_info):
    if (firstFailure == build_info['number']):
        firstFailureTime = build_info['timestamp']
    else:
        failed_build_info = db_get_build_info(job_info['name'],
                                                      firstFailure)
        if (failed_build_info):
            firstFailureTime = failed_build_info['timestamp']
        else:
            firstFailureTime = build_info['timestamp']
    return time_elapsed(firstFailureTime)

def print_build_internal(f,job_info, build_info,verbose):
    print("%-40s #%-4d" % (build_info['name'], build_info['number']),
          end='', file=f)
    if (verbose):
        print(" (%s)" %
              (build_info['description']),
              end='',file=f)
    if (build_info['inProgress']):
        print(" : RUNNING",end='',file=f)
    else:
        r=build_info['result']
        print(" : %s" % r, end='',file=f)
        if (r == "FAILURE"):
            firstFailure=job_info['lastSuccessfulBuild']+1
            elapsedFailureTime = elapsed_failure_time(firstFailure,job_info,build_info)
            print(" (#%d, %s)" %
                  (firstFailure,time_elapsed_str(elapsedFailureTime)),
                  end='',file=f)

        claim_info = get_claim_info(build_info)
        if (claim_info):
            claimedBy = claim_info['claimedBy']
            print(" claimed by %s" % claimedBy,end='',file=f)
            if (verbose):
                reason=claim_info['reason']
                if (reason):
                    print('',file=f)
                    print(textwrap.indent(reason,'    '),end='',file=f)

    print('',file=f)

def print_build(f,job_info,build_info):
    print_build_internal(f,job_info,build_info, True)
    
#
# print build status is an optimized version of print_build that avoids
# loading the build info for successful builds.
#
def print_jobs_status(f,job_infos):
    for ji in job_infos:
        name=ji['name']
        ls=ji['lastSuccessfulBuild']
        lc=ji['lastCompletedBuild']
        if (ls and lc):
            if (ls == lc):
                print("%-40s #%-4d : " % (name,lc),end='',file=f)
                print("SUCCESS",file=f)
            else:
                build_info = get_build_info(name,lc)
                print_build_internal(f,ji,build_info, False)
        else:
            print("%-47s: UNKNOWN" % name, file=f)

def truncate_to_n_lines(s, n):
    lines = s.splitlines()
    return '\n'.join(lines[:n])

scan_log_func = None
def get_scan_log(buildlog):
    global scan_log_func
    fin=io.StringIO(buildlog)
    s=scan_log_func(fin)
    return s

scan_log_limit = 0
def print_scan_log(f,job_info,buildlog):
    global scan_log_limit
    s=get_scan_log(buildlog)
    if (s['summary']):
        if (scan_log_limit > 0):
            print(truncate_to_n_lines(s['summary'],scan_log_limit),file=f)
        else:
            print(s['summary'],file=f)

def print_changeSets(f,build_info):
    changeSets=build_info['changeSets']
    if (len(changeSets)>0):
        print("ChangeSets:",file=f)
        for c in changeSets:
            print("    %s: %s"
                  % (c['authorEmail'],c['commitId']),
                  file=f)
            for a in c['affectedPaths']:
                print("        "+a,file=f)
            print("",file=f)
            print(textwrap.indent(c['comment'],'        '),file=f)

def print_build_summary(f,job_info,build_info,buildlog):
    print_header(f,job_info,build_info)
    print_scan_log(f,job_info,buildlog)

enable_header = False
first_header = True
def print_header(f,job_info,build_info):
    global enable_header, first_header
    name=build_info['name']
    num=build_info['number']
    if (enable_header):
        if (not first_header):
            print("\n",file=f)
        first_header=False
        
        log_header=f"{name} #{num}"
        if (build_info['inProgress']):
            log_header+= " : RUNNING"
        else:
            r=build_info['result']
            log_header+=f" : {r}"
            if (r == "FAILURE"):
                firstFailure=job_info['lastSuccessfulBuild']+1
                elapsedFailureTime = elapsed_failure_time(firstFailure,job_info,build_info)
                elapsed_time = time_elapsed_str(elapsedFailureTime)
                log_header+=f" (#{firstFailure}, {elapsed_time})"

        claimedBy = get_claimedBy(build_info)
        if (claimedBy):
            log_header+=f" claimed by {claimedBy}"


        print(log_header,file=f)
        print('-'*len(log_header),file=f)
    print("",file=f)

def scan_log_callback(f,job_info,build_info):
    name=build_info['name']
    num=build_info['number']
    buildlog=get_build_console(name,num)
    print_build_summary(f,job_info,build_info,buildlog)


def db_scan_log_callback(f,job_info,build_info):
    name=build_info['name']
    num=build_info['number']
    buildlog=db_get_build_log(name,num)
    print_build_summary(f,job_info,build_info,buildlog)

def db_print_log_callback(f,job_info,build_info):
    print_header(f,job_info,build_info)

    name=build_info['name']
    num=build_info['number']
    buildlog=db_get_build_log(name,num)
    print(f,buildlog)

def skip_success(build_info):
    if (build_info['result'] == "SUCCESS"):
        return True
    return False

def kvetch(f,job_info,build_info,buildlog,do_email):
    global enable_header,build_monitor,kvetch_mode
    enable_header=True
    if (do_email):
        print_header(f,job_info,build_info)

    if (kvetch_mode == 'OFF'):
        return

    if (build_info['result']=='SUCCESS'):
        if (build_info['number']-1 == job_info['lastFailedBuild']):
            kvetch_info = db_get_kvetch_info(build_info['name'])
            if (kvetch_info and do_email):
                #TBD: add claimee even if not previously kvetched at?
                send_email(kvetch_info['target'],
                           None,
                           f"kvetch: {build_info['fullDisplayName']} successful again",
                           build_info['url']+"\n")
                # Clear out the kvetch_info
                kvetch_info['build'] = -1
                kvetch_info['target'] = ""
                kvetch_info['timestamp'] = datetime.datetime.now().timestamp() * 1000
                kvetch_info['level'] = 1
                db_set_kvetch_info(kvetch_info)
            else:
                print(f"{build_info['fullDisplayName']} successful again")
                if (kvetch_info):
                    print(f"let {kvetch_info['target']} know")
        return

    email_to = None
    email_cc = None
    body=""
    firstFailure=job_info['lastSuccessfulBuild']+1
    elapsedFailureTime = elapsed_failure_time(firstFailure,job_info,build_info)
    claimedBy = get_claimedBy(build_info)
    developers=get_developers(build_info)

    msg=io.StringIO()
    s=get_scan_log(buildlog)

    if (s['blame'] == "System"):
        email_to = build_monitor
        body+="Dear Build Monitors,\n\n"
        body+="This build failure looks like an infrastructure issue.\n"
        if (claimedBy):
            if (claimedBy == "SYSTEM"):
                body+="It has already claimed by System\n"
            else:
                body+=f"It is currently claimed by {claimedBy}. Can you look to see if the claim should be reset to SYSTEM?\n"
            body+=build_info['url'] + "\n"
        else:
            body+="Please claim it: "+ build_info['url'] + "\n\n"
    else:
        if (claimedBy):
            if (claimedBy == "SYSTEM"):
                email_to = build_monitor
                body+="Dear Build Monitors\n\n"
                body+="This build is still failing and is assigned to SYSTEM, but it does not look like a system failure to me. Can you take a look?\n"
                body+=build_info['url'] + "\n"
            else:
                email_to = get_email_of(claimedBy)
                body+="Dear " + claimedBy + ",\n\n"

                if (kvetch_mode == "DEBUG"):
                    body+=f"TBD: sending to {build_monitor} instad of {email_to}\n"
                    email_to = build_monitor # TBD: claimedBy

                if (elapsedFailureTime.days > 1):
                    boss=get_lead_of(claimedBy)
                    email_cc = get_email_of(boss)

                    if (kvetch_mode == "DEBUG"):
                        body+=f"TBD: cc {build_monitor} instead of {email_cc}\n"
                        email_cc = build_monitor # TBD: boss

                body+="This build is still failing. Please make fixing it your top priority. If the failure is no longer yours, please reassign the claim.\n"
                body+=build_info['url'] + "\n"
        else:
            if (firstFailure < build_info['number']):
                email_to = build_monitor
                body+="Dear Build Monitor,\n\n"
                body+="This build failure looks like a developer issue, but it was not claimed. Can you take a look?\n"
            elif (len(developers)==0):
                email_to = build_monitor
                body+="Dear Build Monitor,\n\n"
                body+="This build failure looks like a developer issue, but there are no commits. Can you take a look?\n"
            else:
                dev_emails=",".join(developers)
                email_to = dev_emails
                body+=f"Dear {dev_emails},\n\n"

                if (kvetch_mode == "DEBUG"):
                    body+=f"TBD: Sending to {build_monitor} instead {email_to}\n"
                    email_to = build_monitor # TBD: dev_emails

                body+="This build failure looks like a developer issue. Please claim it if it is yours:\n"

            body+=build_info['url'] + "\n"

    body+="\nSincerely,\nKvetch\n\n"

    kvetch_info = db_get_kvetch_info(build_info['name'])
    # Only skip kvetching if we are sending an email
    if (kvetch_info and do_email):
        if (kvetch_info['build']==build_info['number']):
            if (kvetch_info['target']==email_to):
                elapsedKvetchTime=time_elapsed(kvetch_info['timestamp'])
                if ((elapsedKvetchTime.days < 1) and
                    (elapsedKvetchTime.seconds < (23*(60*60)))):
                    # has not been over a day yet, do not kvetch again
                    print("Skipping kvetch for %s #%d, last %s ago" %
                          (build_info['name'],
                           build_info['number'],
                           time_elapsed_str(elapsedKvetchTime)),
                          file=f)
                    return
    else:
        kvetch_info={}
        kvetch_info['jobName']=build_info['name']

    kvetch_info['build'] = build_info['number']
    kvetch_info['target'] = email_to
    kvetch_info['timestamp'] = datetime.datetime.now().timestamp() * 1000
    kvetch_info['level'] = 1

    print_header(msg,job_info,build_info)
    if (s['summary']):
        print(s['summary'],file=msg)
    print_changeSets(msg,build_info)

    subject="Kvetch:"
    subject+=" "+build_info['fullDisplayName']
    body+=msg.getvalue()
    if (do_email):
        send_email(email_to, email_cc, subject, body)
        db_set_kvetch_info(kvetch_info)
    else:
        print(subject,file=f)
        print(body,file=f)

def db_kvetch_internal_callback(f,job_info,build_info, do_email):
    name=build_info['name']
    num=build_info['number']
    buildlog=db_get_build_log(name,num)
    kvetch(f,job_info,build_info,buildlog,do_email)

def db_kvetch_print_callback(f,job_info,build_info):
    db_kvetch_internal_callback(f,job_info,build_info,False)

def db_kvetch_email_callback(f,job_info,build_info):
    db_kvetch_internal_callback(f,job_info,build_info,True)

#
# Main Program
#

if __name__ == "__main__":
    import getopt

    opts,args = getopt.getopt(sys.argv[1:], 'b:c:j:v:adfklmnqrsx')

    if len(args) > 0:
        print("Usage: %s" % sys.argv[0])
        sys.exit(1)

    config_name=None
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
        elif o == "-c":
            config_name = a

    opts = dict(opts)

    if (config_name):
        config = find_and_load_json_config(config_name,[])
    else:
        config = find_and_load_json_config("kvetch.json")
    jenkins_url=config['jenkins_url']
    jenkins_auth=config['jenkins_auth']
    db_path=config['db_path']
    scan_log_func=load_func_from_file(config['scanlogpy'],config['scanlogfunc'])
    org_path=config['org_chart']
    from_email=config['from_email']
    smtp_server=config['smtp_server']
    smtp_port=config['smtp_port']
    build_monitor=config['build_monitor']
    kvetch_mode=config['kvetch_mode']

    init(org_path)

    if (view_name):
        try:
            jobs_from_view=get_jobs(view_name)
        except Exception as e:
            print("Error: unable to load view: %s" % e)
            sys.exit(1)
        job_names.extend(get_jobs(view_name))

    try:
        job_infos = get_job_infos(job_names,build_ids)
    except Exception as e:
        print("Error: unable to load jobs: %s" % e)
        sys.exit(1)

    #
    # These options only pull data from Jenkins
    #
    if '-s' in opts:
        if (len(build_ids)>0):
            print("ERROR: build ids not compatible with status")
            sys.exit(1)
        print_jobs_status(sys.stdout,job_infos)
        sys.exit(0)
    elif '-a' in opts:
        for_each_build(job_infos, None, print_build_json,sys.stdout)
        sys.exit(0)
    elif '-q' in opts:
        for_each_build(job_infos, None, print_build,sys.stdout)
        sys.exit(0)
    elif '-r' in opts:
        # This is for triage at end of Job in Jenkins, no DB involved
        for_each_build(job_infos, None, scan_log_callback,sys.stdout)
        sys.exit(0)

    #
    # Populate new data into DB from Jenkins unless specifically suspended
    #
    if (not '-n' in opts):
        #
        # Regardless of the builds selected by the user, we want to populate
        # all build history.
        #
        pjob_infos = get_job_infos(job_names,[])

        if (for_each_build(pjob_infos, skip_build, record_build,sys.stdout)):
            print('')
            commit_sqlite()

    #
    # These options only pull data from the DB
    #
    if (count_builds(job_infos) > 1):
        enable_header = True
        scan_log_limit = 30

    out=sys.stdout
    if '-m' in opts:
        out = io.StringIO()
        

    whatis=None
    build_filter=None
    if '-f' in opts:
        build_filter=skip_success

    if '-d' in opts:
        whatis="status"
        db_for_each_build(job_infos,build_filter,print_build,out)
    elif '-l' in opts:
        whatis="build log"
        db_for_each_build(job_infos,build_filter,db_print_log_callback,out)
    elif '-x' in opts:
        whatis="scan log"
        db_for_each_build(job_infos,build_filter,db_scan_log_callback,out)
    elif '-k' in opts:
        callback=db_kvetch_print_callback
        if '-m' in opts:
            callback=db_kvetch_email_callback
        db_for_each_build(job_infos,build_filter,callback,sys.stdout)


    if (whatis):
        if '-m' in opts:
            subject="Kvetch:"
            if (view_name):
                subject+=" "+view_name
            else:
                for job in job_names:
                    subject+=" "+job

            subject+=" "+whatis
            body = out.getvalue()
            if (body == ""):
                body = "All builds were successful"
            send_email(build_monitor, None, subject, body)
        
    finish()
    sys.exit(0)

#
# Unit tests run with: python3 -m unittest <filename.py>
#
import unittest

class MyTestCase(unittest.TestCase):
    def test_org(self):
        init_org("examples/org.json")
        self.assertEqual('waltc',get_lead_of("garyv"))
        m=get_members_of("dsmith")
        self.assertEqual('coleenp',m[0])
        self.assertEqual('judyw',m[1])
        self.assertEqual('prem',m[2])
        self.assertEqual(3,len(m))
