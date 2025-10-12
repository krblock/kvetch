Installation Guide

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
