#!/usr/bin/env python3

# Copyright 2025 Thinker Cats (thinkercats.com)
#
# Licensed under BSD 3-Clause License

import os
import re
import sys
from enum import IntEnum, auto

class State(IntEnum):
    Prologue = auto()
    CheckOut = auto()
    Build = auto()
    Test = auto()
    Epilogue = auto()
    Summary = auto()
    
state = State.Prologue
log = {}

def add_logging(line):
    global log,state
    if (log.get(state) is None):
        log[state]=""
    log[state]+=line+"\n"

# Define actions for each pattern
def handle_begin_checkout(line,timestamp,match):
    global state
    state = State.CheckOut

def handle_begin_build(line,timestamp,match):
    global state
    state = State.Build

def handle_begin_epilogue(line,timestamp,match):
    global state
    state = State.Epilogue

def handle_generic_error(line,timestamp,match):
    add_logging(f"[ERROR] {line}")

def handle_noprefix_error(line,timestamp,match):
    add_logging(f"{line}")

def ignore_pattern(line,timestamp,match):
    None

pattern_actions = {
    # Patterns for state transition
    re.compile(r"^git clone"): handle_begin_checkout,
    re.compile(r"make -f all.mk all"): handle_begin_build,
    re.compile(r"^Testing complete"): handle_begin_epilogue,

    # Patterns that look like failures, but are not
    re.compile(r"^ERROR: Skipping something permanently disabled"): ignore_pattern,

    # Patterns to things that looks like failures
    re.compile(r": \*\*\*"): handle_generic_error,
    re.compile(r"^\[ERROR\]"): handle_noprefix_error,
    re.compile(r"^ERROR:"): handle_noprefix_error,
    re.compile(r"^ssh: (.*)"): handle_generic_error,
    re.compile(r"^rsync: (.*)"): handle_generic_error,
    re.compile(r"^rsync error: (.*)"): handle_generic_error,
    re.compile(r"^FATAL: (.*)"): handle_generic_error,
    re.compile(r"^fatal: (.*)"): handle_generic_error,
    re.compile(r"^Caused: (.*)"): handle_generic_error,
    re.compile(r":\d+:\d+: error: "): handle_generic_error,
}


def scan_log(f):
    global state,log
    state = State.Prologue    
    log={}
    summary={}
    count=0
    # Skip off timestamp for easier reading
    lpattern = r"^(\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\])?\s*(.*)"
    for line in f:
        count+=1
        lmatch = re.match(lpattern, line)
        timestamp = lmatch.group(1)
        message = lmatch.group(2)
        for pattern, action in pattern_actions.items():
            match = pattern.search(message)
            if match:
                action(message,timestamp,match)
                break

    state = State.Summary
    no_logging = True
    for s in State:
        if (s == State.Summary):
            continue
        if (log.get(s) is not None):
            add_logging(f"{s.name}")
            add_logging('-'*len(s.name))
            add_logging(log[s])
            no_logging = False
    if (no_logging):
        add_logging("No known failures were detected")

    summary['count']=count
    summary['log']=log[State.Summary]
    return summary

#
# Main Program
#

if __name__ == "__main__":
    import getopt

    opts,args = getopt.getopt(sys.argv[1:], 'l:')

    if len(args) > 0:
        print("Usage: %s" % sys.argv[0])
        sys.exit(1)

    log_name = None
    for o, a in opts:
        if o == "-l":
            log_name = a

    opts = dict(opts)
    
    if (log_name):
        f = open(log_name,'r')
    else:
        f = sys.stdin

    summary=scan_log(f)

    f.close()

    print(summary('log'),end='')
    sys.exit(0)
