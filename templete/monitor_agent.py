#!/usr/bin/env python3
import urllib.parse
import urllib.request
import traceback
import psutil
import datetime
import time
import json

def get_rq():
    now_time = datetime.datetime.now()
    curr_str = datetime.datetime.strftime(now_time, '%Y-%m-%d %H:%M:%S')
    return curr_str

def gather():
    d_host={}
    d_host['ip']='192.168.1.48'
    d_host['port']='3306'
    d_host['rq']=get_rq()
    d_host['cpu_usage']=psutil.cpu_percent(None)
    d_host['memory_usage']=psutil.virtual_memory().percent
    disk_read_bytes_ref_value=psutil.disk_io_counters()[2]
    disk_write_bytes_ref_value=psutil.disk_io_counters()[3]
    net_sent_bytes_ref_value=psutil.net_io_counters()[0]
    net_recv_bytes_ref_value=psutil.net_io_counters()[1]  
    time.sleep(1)
    d_host['disk_read_bytes'] =int(round((psutil.disk_io_counters()[2]-disk_read_bytes_ref_value)/1024/1024,0))
    d_host['disk_write_bytes']=int(round((psutil.disk_io_counters()[3]-disk_write_bytes_ref_value)/1024/1024,0))
    d_host['net_sent_bytes']  =int(round((psutil.net_io_counters()[0]-net_sent_bytes_ref_value)/1024/1024,0)) 
    d_host['net_resv_bytes']  =int(round((psutil.net_io_counters()[1]-net_recv_bytes_ref_value)/1024/1024,0))
    return d_host
  
def send_request():
  d_host=gather()
  if d_host['cpu_usage']!=0 or d_host['memory_usage']!=0:
     url = 'http://192.168.1.161:80/monitor_agent'
     v_json_host = json.dumps(d_host)
     #print('v_json_host=',v_json_host)
     values = {
       'host' : v_json_host
     }
     data = urllib.parse.urlencode(values).encode(encoding='UTF-8')
     req = urllib.request.Request(url, data)
     response = urllib.request.urlopen(req)
     the_page = response.read()
     #print(the_page.decode("utf-8"))

while True:
  try:
     send_request()
  except:
     #print(traceback.format_exc())
     pass
  time.sleep(30)

