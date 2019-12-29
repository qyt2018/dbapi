export PYTHON3_HOME=/usr/local/python3.6
export LD_LIBRARY_PATH=${PYTHON3_HOME}/lib
nohup $PYTHON3_HOME/bin/python3 /home/hopson/apps/usr/webserver/dbapi/dbapi.py $1 &
