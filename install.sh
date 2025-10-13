#!/bin/sh
INSTALLDIR=$1
JENKINS_URL=$2

if [ "$INSTALLDIR" = "" -o "$JENKINS_URL" = "" ]; then
  echo "usage: $0 <install dir> <jenkins_url>"
  exit 1
fi

SCRIPTDIR=`dirname $0`
if [ `echo $SCRIPTDIR | cut -b1` != "/" ]; then
  SCRIPTDIR="`pwd`/$SCRIPTDIR"
fi

mkdir $INSTALLDIR
cd $INSTALLDIR

cp $SCRIPTDIR/src/kvetch.py .
cp -r $SCRIPTDIR/examples config
python3 -m venv venv
. venv/bin/activate
pip install python-jenkins
mv config/kvetch.json config/kvetch.json.orig
echo "$JENKINS_URL"
cat config/kvetch.json.orig | \
    sed -e "s|<my jenkins URL>|$JENKINS_URL|" > config/kvetch.json
rm -f config/kvetch.json.orig

if [ ! -r ~/.ssh/jenkins-token ]; then
    echo "Make sure to configure your jenkins authentication token"
fi
