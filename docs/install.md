# Installation Guide

```
$ git clone <kvetch repo> kvetch-git
$ mkdir kvetch
$ cd kvetch
$ cp ../kvetch-git/src/kvetch.py .
$ cp -r ../kvetch-git/examples config
$ python3 -m venv venv
$ . venv/bin/activate
$ pip install python-jenkins
```

edit config/kvetch.json to point to your Jenkins server

Create an API Token in Jenkins, by going to https:<your jenkins server>/user/<username>/security
Place the token in ~/.ssh/jenkins-token

Test to see if it is working:

```
$ ./kvetch.py -j "<Jenkins Job Name>" -s
<Job Name>                     #<Build Number>  : <Status>
```

## Customizing scanlog.py

Kvetch provides an interface to Jenkins, a schema for SQLite, and a framework for moving the data between the two and reporting. Creating a summary of a build, a scan log, is the reponsibility of scanlog.py. A scan log contains the important details about a build: compilation, test, and infrastructure failures. Parsing a build log to produce a scan log is not particularly difficult process and Kvetch provides a framework for doing so and a sample.

The suggested framework is this: divide your build log up into sections to cover the interesting phases of your build. Typical phases and what is provided in the example are: prologue, checkout, build, test, epilogue, and summary. You need to add regular expressions to tell scanlog when you are transitioning to different phases. You then add regular expressions for things that are important for reporting in the scanlog and scanlog will record them in the log of the appropriate phase.

It is not necessary to follow the framework provided. The only requirement is that the scan function return a dictionary of useful information about the scanlog that you want Kvetch to be able to report. Currently the only information Kvetch will report (-f) is the 'summary' information in the dictionary, but this limitation will be lifted shortly.
