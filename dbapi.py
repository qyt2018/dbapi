#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time : 2019/9/16 9:32
# @Author : 马飞
# @File : dbapi.py
# @Func : dbops_api Server 提供数据库备份、同步API。
# @Software: PyCharm
import tornado.ioloop
import tornado.web
import tornado.options
import tornado.httpserver
import tornado.locale
from   tornado.options  import define, options
import datetime,json
import pymysql
import paramiko
import os,sys
import traceback
from   crontab import CronTab

def get_time():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def print_dict(config):
    print('-'.ljust(85,'-'))
    print(' '.ljust(3,' ')+"name".ljust(20,' ')+'value')
    print('-'.ljust(85,'-'))
    for key in config:
        print(' '.ljust(3,' ')+key.ljust(20,' ')+'='+str(config[key]))
    print('-'.ljust(85,'-'))

def get_ds_mysql(ip,port,service ,user,password):
    conn = pymysql.connect(host=ip, port=int(port), user=user, passwd=password, db=service,
                           charset='utf8',cursorclass = pymysql.cursors.DictCursor)
    return conn

def get_ds_mysql2(ip,port,service ,user,password):
    conn = pymysql.connect(host=ip, port=int(port), user=user, passwd=password, db=service,
                           charset='utf8')
    return conn

def get_db_mysql(config):
    return get_ds_mysql(config['db_ip'],config['db_port'],config['db_service'],config['db_user'],config['db_pass'])

def get_db_mysql2(config):
    return get_ds_mysql2(config['db_ip'],config['db_port'],config['db_service'],config['db_user'],config['db_pass'])

def aes_decrypt(db,p_password,p_key):
    cr = db.cursor()
    sql="""select aes_decrypt(unhex('{0}'),'{1}') as password """.format(p_password,p_key[::-1])
    cr.execute(sql)
    rs=cr.fetchone()
    db.commit()
    cr.close()
    db.close()
    print('aes_decrypt=',str(rs['password'],encoding = "utf-8"))
    return str(rs['password'],encoding = "utf-8")

def write_log(msg):
    file_name   = '/tmp/dbapi_{0}.log'.format(options.port)
    file_handle = open(file_name, 'a+')
    file_handle.write(msg + '\n')
    file_handle.close()

def get_file_contents(filename):
    file_handle = open(filename, 'r')
    line = file_handle.readline()
    lines = ''
    while line:
        lines = lines + line
        line = file_handle.readline()
    lines = lines + line
    file_handle.close()
    return lines

def db_config():
    config={}
    config['db_ip']      = '10.2.39.18'
    config['db_port']    = '3306'
    config['db_user']    = 'puppet'
    config['db_pass']    = 'Puppet@123'
    config['db_service'] = 'puppet'
    config['db_mysql']   =  get_db_mysql(config)
    return config

def db_config2():
    config={}
    config['db_ip']      = '10.2.39.18'
    config['db_port']    = '3306'
    config['db_user']    = 'puppet'
    config['db_pass']    = 'Puppet@123'
    config['db_service'] = 'puppet'
    config['db_mysql']   =  get_db_mysql2(config)
    return config

def db_config_info():
    config={}
    config['db_ip']      = '10.2.39.18'
    config['db_port']    = '3306'
    config['db_user']    = 'puppet'
    config['db_pass']    = '7D86F7A83E38AD4DFB15C0AFEFF7D310'
    config['db_service'] = 'puppet'
    return config

def update_backup_status(p_tag):
    config = db_config()
    db     = config['db_mysql']
    cr     = db.cursor()
    result = get_db_config(p_tag)
    if result['code']!=200:
       return result
    v_cmd   = 'ps -ef |grep {0} | grep -v grep |wc -l'.format(p_tag)
    print(v_cmd)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)

    #execute command
    stdin, stdout,stderr=ssh.exec_command(v_cmd)
    #get result
    res, err = stdout.read(), stderr.read()
    ret = (res if res else err).decode().replace('\n','')
    ssh.close()
    #update table:t_db_config task_status column
    print(p_tag,'A'+ret+'B',ret==0,ret=='0',v_cmd)
    if ret=='0':
       cr.execute("update t_db_config set task_status=0 where db_tag='{0}'".format(p_tag))
       db.commit()
       cr.close()
       result['code'] = 0
       result['msg'] = '已停止!'
    else:
       cr.execute("update t_db_config set task_status=1 where db_tag='{0}'".format(p_tag))
       db.commit()
       cr.close()
       result['code'] = 1
       result['msg'] = '运行中!'
    return result

def get_task_tags():
    config = db_config()
    db     = config['db_mysql']
    cr     = db.cursor()
    cr.execute("SELECT  a.db_tag FROM t_db_config a  WHERE a.status='1'")
    rs = cr.fetchall()
    print(rs,type(rs))
    cr.close()
    return rs

def get_db_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    result = {}
    result['code'] = 200
    result['msg'] = ''

    #检测同步服务器是否有效
    if check_server_sync_status(p_tag) > 0:
        result['code'] = -1
        result['msg'] = '服务器已禁用!'
        return result

    #检测同步标识是否存在
    if check_db_config(p_tag) == 0:
        result['code'] = -1
        result['msg'] = '备份标识不存在!'
        return result

    #任务已禁用
    if check_backup_task_status(p_tag) > 0:
        result['code'] = -1
        result['msg'] = '备份任务已禁用!'
        return result

    cr.execute('''SELECT  a.db_tag,
                          c.ip   AS db_ip,
                          c.port AS db_port,
                          c.user AS db_user,
                          c.password AS db_pass,
                          a.expire,
                          a.bk_base,a.script_path,a.script_file,a.bk_cmd,a.run_time,
                          b.server_ip,b.server_port,b.server_user,b.server_pass,
                          a.comments,a.python3_home,a.backup_databases,a.api_server,a.status
                FROM t_db_config a,t_server b,t_db_source c
                WHERE a.server_id=b.id 
                  AND a.db_id=c.id
                  AND a.db_tag='{0}' 
                  AND b.status='1'
               '''.format(p_tag))
    rs=cr.fetchone()
    result['msg'] = rs
    cr.close()
    return result

def get_db_sync_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    result = {}
    result['code'] = 200
    result['msg'] = ''

    #检测同步服务器是否有效
    if check_server_sync_status(p_tag)>0:
       result['code'] = -1
       result['msg'] = '同步服务器已禁用!'
       return result

    #检测同步标识是否存在
    if check_db_sync_config(p_tag)==0:
       result['code'] = -2
       result['msg'] = '同步标识不存在!'
       return result

    #任务已禁用
    if check_sync_task_status(p_tag) > 0:
       result['code'] = -3
       result['msg'] = '同步任务已禁用!'
       return result

    cr.execute('''SELECT  a.sync_tag,
                          a.sync_ywlx,
                          (select dmmc from t_dmmx where dm='08' and dmm=a.sync_ywlx) as sync_ywlx_name,
                          a.sync_type,
                          (select dmmc from t_dmmx where dm='09' and dmm=a.sync_type) as sync_type_name,
                          CASE WHEN c.service='' THEN 
                            CONCAT(c.ip,':',c.port,':',a.sync_schema,':',c.user,':',c.password)
                          ELSE
                            CONCAT(c.ip,':',c.port,':',c.service,':',c.user,':',c.password)
                          END AS sync_db_sour,                          
                          CASE WHEN d.service='' THEN 
                            CONCAT(d.ip,':',d.port,':',a.sync_schema,':',d.user,':',d.password)
                          ELSE
                            CONCAT(d.ip,':',d.port,':',d.service,':',d.user,':',d.password)
                          END AS sync_db_dest,                          
                          a.server_id,
                          b.server_desc,
                          a.run_time,
                          a.api_server,
                          LOWER(a.sync_table) AS sync_table,a.batch_size,a.batch_size_incr,a.sync_gap,a.sync_col_name,
                          a.sync_col_val,a.sync_time_type,a.script_path,a.script_file,a.comments,a.python3_home,
                          a.status,b.server_ip,b.server_port,b.server_user,b.server_pass                         
                FROM t_db_sync_config a,t_server b,t_db_source c,t_db_source d
                WHERE a.server_id=b.id 
                  AND a.sour_db_id=c.id
                  AND a.desc_db_id=d.id
                  AND a.sync_tag ='{0}' 
                  ORDER BY a.id,a.sync_ywlx
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    result['msg']=rs
    return result

def get_db_transfer_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    result = {}
    result['code'] = 200
    result['msg'] = ''

    #检测传输服务器是否有效
    if check_server_transfer_status(p_tag)>0:
       result['code'] = -1
       result['msg'] = '传输服务器已禁用!'
       return result

    #检测同步标识是否存在
    if check_db_transfer_config(p_tag)==0:
       result['code'] = -1
       result['msg'] = '传输标识不存在!'
       return result

    cr.execute('''SELECT  a.transfer_tag,
                          CONCAT(c.ip,':',c.port,':',a.sour_schema,':',c.user,':',c.password) AS transfer_db_sour,                          
                          CONCAT(d.ip,':',d.port,':',a.dest_schema,':',d.user,':',d.password) AS transfer_db_dest,  
                          a.server_id,
                          b.server_desc,
                          a.api_server,
                          LOWER(a.sour_table) AS sour_table,
                          a.sour_where,
                          a.script_path,
                          a.script_file,
                          a.batch_size,
                          a.comments,
                          a.python3_home,
                          a.status,
                          b.server_ip,
                          b.server_port,
                          b.server_user,
                          b.server_pass                         
            FROM t_db_transfer_config a,t_server b,t_db_source c,t_db_source d
            WHERE a.server_id=b.id 
            AND a.sour_db_id=c.id
            AND a.dest_db_id=d.id
            AND a.transfer_tag ='{0}' 
            ORDER BY a.id
            '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    result['msg']=rs
    return result

def get_db_archive_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    result = {}
    result['code'] = 200
    result['msg'] = ''

    #检测传输服务器是否有效
    if check_server_archive_status(p_tag)>0:
       result['code'] = -1
       result['msg'] = '归档服务器已禁用!'
       return result

    #检测同步标识是否存在
    if check_db_monitor_config(p_tag)==0:
       result['code'] = -1
       result['msg'] = '归档标识不存在!'
       return result

    cr.execute('''SELECT  a.archive_tag,
                      CONCAT(c.ip,':',c.port,':',a.sour_schema,':',c.user,':',c.password) AS archive_db_sour,                          
                      CONCAT(d.ip,':',d.port,':',a.dest_schema,':',d.user,':',d.password) AS archive_db_dest,  
                      a.server_id,
                      b.server_desc,
                      a.api_server,
                      LOWER(a.sour_table) AS sour_table,
                      a.archive_time_col,
                      a.archive_rentition,
                      a.rentition_time,
                      a.rentition_time_type,
                      e.dmmc as rentition_time_type_cn,
                      a.if_cover,
                      a.script_path,
                      a.script_file,
                      a.run_time,
                      a.batch_size,
                      a.comments,
                      a.python3_home,
                      a.status,
                      b.server_ip,
                      b.server_port,
                      b.server_user,
                      b.server_pass                         
                FROM t_db_archive_config a,t_server b,t_db_source c,t_db_source d,t_dmmx e
                WHERE a.server_id=b.id 
                AND a.sour_db_id=c.id
                AND a.dest_db_id=d.id
                and a.rentition_time_type=e.dmm
                and e.dm='20'
                AND a.archive_tag ='{0}' 
                ORDER BY a.id
            '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    result['msg']=rs
    return result

def get_itmes_from_templete_ids(p_templete):
    config = db_config()
    db  = config['db_mysql']
    cr  = db.cursor()
    sql = '''SELECT index_code FROM t_monitor_index
              WHERE id IN(SELECT index_id FROM `t_monitor_templete_index` 
                           WHERE INSTR('{0}',templete_id)>0) 
                 AND STATUS='1'
          '''.format(p_templete)
    cr.execute(sql)
    rs=cr.fetchall()
    t=''
    for i in rs:
       t=t+i['index_code']+','
    cr.close()
    return t[0:-1]

def get_db_monitor_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    result = {}
    result['code'] = 200
    result['msg'] = ''

    #检测传输服务器是否有效
    if check_server_monitor_status(p_tag)>0:
       result['code'] = -1
       result['msg'] = '采集服务器已禁用!'
       return result

    #检测同步标识是否存在
    if check_db_monitor_config(p_tag)==0:
       result['code'] = -1
       result['msg'] = '监控标识不存在!'
       return result

    cr.execute('''SELECT  a.task_tag,
                        a.comments,
                        a.templete_id,
                        a.server_id,
                        a.db_id,
                        a.run_time,
                        a.python3_home,
                        a.api_server,
                        a.script_path,
                        a.script_file,
                        a.status,
                        b.server_ip,
                        b.server_port,
                        b.server_user,
                        b.server_pass,
                        b.server_desc,   
                        b.market_id,
                        c.ip        AS db_ip,
                        c.port      AS db_port,
                        c.service   AS db_service,
                        c.user      AS db_user,
                        c.password  AS db_pass,
                        c.db_type   AS db_type              
                FROM t_monitor_task a 
                   JOIN t_server b ON a.server_id=b.id 
                   LEFT JOIN t_db_source c  ON  a.db_id=c.id  
                where a.task_tag ='{0}' 
                ORDER BY a.id
            '''.format(p_tag))

    rs=cr.fetchone()
    cr.close()
    rs['templete_indexes'] = get_itmes_from_templete_ids(rs['templete_id'])
    result['msg']=rs
    return result


def get_datax_sync_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    result = {}
    result['code'] = 200
    result['msg'] = ''

    #检测同步服务器是否有效
    if check_datax_server_sync_status(p_tag)>0:
       result['code'] = -1
       result['msg'] = '同步服务器已禁用!'
       return result

    #检测同步标识是否存在
    if check_datax_sync_config(p_tag)==0:
       result['code'] = -2
       result['msg'] = '同步标识不存在!'
       return result

    #任务已禁用
    if check_datax_sync_task_status(p_tag) > 0:
       result['code'] = -3
       result['msg'] = '同步任务已禁用!'
       return result

    cr.execute('''SELECT  a.id,
                          a.sync_tag,
                          a.sync_ywlx,
                          CASE WHEN c.service='' THEN 
                            CONCAT(c.ip,':',c.port,':',a.sync_schema,':',c.user,':',c.password)
                          ELSE
                            CONCAT(c.ip,':',c.port,':',c.service,':',c.user,':',c.password)
                          END AS sync_db_sour,                          
                          a.zk_hosts,
                          a.python3_home,                
                          a.server_id,a.run_time,a.api_server,
                          LOWER(a.sync_table) AS sync_table,a.sync_gap,
                          a.sync_time_type,a.script_path,a.comments,
                          a.status,
                          b.server_ip,b.server_port,b.server_user,b.server_pass,
                          a.hbase_thrift,
                          a.sync_hbase_table,
                          a.datax_home,
                          a.sync_incr_col,
                          a.sync_table,
                          a.sync_incr_where
                    FROM t_datax_sync_config a,t_server b,t_db_source c
                    WHERE a.server_id=b.id 
                      AND a.sour_db_id=c.id
                      AND a.sync_tag ='{0}' 
                      ORDER BY a.id,a.sync_ywlx
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    result['msg']=rs
    return result

def check_db_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_db_config where db_tag='{0}'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_db_sync_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_db_sync_config where sync_tag='{0}'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_db_transfer_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_db_transfer_config where transfer_tag='{0}'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']


def check_db_archive_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_db_archive_config where archive_tag='{0}'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_db_monitor_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_monitor_task where task_tag='{0}'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']


def check_datax_sync_config(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_datax_sync_config where sync_tag='{0}'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_server_sync_status(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_db_sync_config a,t_server b 
                  where a.server_id=b.id and a.sync_tag='{0}' and b.status='0'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_server_transfer_status(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_db_transfer_config a,t_server b 
                  where a.server_id=b.id and a.transfer_tag='{0}' and b.status='0'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_server_archive_status(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_db_archive_config a,t_server b 
                  where a.server_id=b.id and a.archive_tag='{0}' and b.status='0'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_server_monitor_status(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_monitor_task a,t_server b 
                  where a.server_id=b.id and a.task_tag='{0}' and b.status='0'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_datax_server_sync_status(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_db_sync_config a,t_server b 
                  where a.server_id=b.id and a.sync_tag='{0}' and b.status='0'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_sync_task_status(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_db_sync_config a,t_server b 
                  where a.server_id=b.id and a.sync_tag='{0}' and a.status='0'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_datax_sync_task_status(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_datax_sync_config a,t_server b 
                  where a.server_id=b.id and a.sync_tag='{0}' and a.status='0'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_backup_task_status(p_tag):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from t_db_config a,t_server b 
                  where a.server_id=b.id and a.db_tag='{0}' and a.status='0'
               '''.format(p_tag))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def check_tab_exists(p_tab,p_where):
    config=db_config()
    db=config['db_mysql']
    cr=db.cursor()
    cr.execute('''select count(0) from {0} {1}'''.format(p_tab,p_where))
    rs=cr.fetchone()
    cr.close()
    return  rs['count(0)']

def save_sync_log(config):
    result = {}
    result['code'] = 200
    result['msg'] = 'success'
    db=db_config()['db_mysql']
    cr=db.cursor()
    v_sql='''insert into t_db_sync_tasks_log(sync_tag,create_date,duration,amount) values('{0}','{1}','{2}','{3}')
          '''.format(config['sync_tag'],config['create_date'],config['duration'],config['amount'])

    write_log(get_time())
    write_log(v_sql)
    cr.execute(v_sql)
    db.commit()
    cr.close()
    return result


def save_datax_sync_log(config):
    result = {}
    result['code'] = 200
    result['msg'] = 'success'
    db=db_config()['db_mysql']
    cr=db.cursor()
    v_sql='''insert into t_datax_sync_log(sync_tag,create_date,table_name,duration,amount) values('{0}','{1}','{2}','{3}','{4}')
          '''.format(config['sync_tag'],config['create_date'],config['table_name'],config['duration'],config['amount'])
    print('save_datax_sync_log=',v_sql)
    write_log(get_time())
    write_log(v_sql)
    cr.execute(v_sql)
    db.commit()
    cr.close()
    return result


def save_transfer_log(config):
    result = {}
    result['code'] = 200
    result['msg'] = 'success'
    db = db_config()['db_mysql']
    cr = db.cursor()
    v_where = " where transfer_tag='{0}' and create_date ='{1}'".format(config['transfer_tag'], config['create_date'])
    if check_tab_exists('t_db_transfer_log', v_where) == 0:
        v_sql='''insert into t_db_transfer_log(transfer_tag,table_name,create_date,duration,amount,percent) values('{0}','{1}','{2}','{3}','{4}','{5}')
              '''.format(config['transfer_tag'],config['table_name'],config['create_date'],config['duration'],config['amount'],config['percent'])
    else:
        v_sql = '''update t_db_transfer_log
                            set table_name   = '{0}',
                                duration     = '{1}',
                                amount       = '{2}',
                                percent      = '{3}'
                          where transfer_tag = '{4}' and create_date='{5}'
                      '''.format(config['table_name'],config['duration'],config['amount'], config['percent'],config['transfer_tag'],config['create_date'])

    #print(v_sql)
    cr.execute(v_sql)
    db.commit()
    cr.close()
    return result

def save_archive_log(config):
    result = {}
    result['code'] = 200
    result['msg'] = 'success'
    db = db_config()['db_mysql']
    cr = db.cursor()
    v_where = " where archive_tag='{0}' and create_date ='{1}'".format(config['archive_tag'], config['create_date'])
    if check_tab_exists('t_db_archive_log', v_where) == 0:
        v_sql='''insert into t_db_archive_log(archive_tag,table_name,create_date,start_time,end_time,duration,amount,percent,message) 
                    values('{0}','{1}','{2}','{3}','{4}','{5}','{6}','{7}','{8}')
              '''.format(config['archive_tag'],config['table_name'],config['create_date'],
                         config['start_time'],config['end_time'],config['duration'],
                         config['amount'],config['percent'],config['message'])
    else:
        v_sql = '''update t_db_archive_log
                            set table_name   = '{0}',
                                duration     = '{1}',
                                amount       = '{2}',
                                percent      = '{3}',
                                start_time   = '{4}',
                                end_time     = '{5}',
                                message      = '{6}'
                          where archive_tag = '{7}' and create_date='{8}'
                      '''.format(config['table_name'],config['duration'],config['amount'],
                                 config['percent'],config['start_time'],config['end_time'],
                                 config['message'],config['archive_tag'],config['create_date'])

    print('save_archive_log=',v_sql)
    cr.execute(v_sql)
    db.commit()
    cr.close()
    return result

def save_monitor_log(config):
    result = {}
    result['code'] = 200
    result['msg'] = 'success'
    db = db_config()['db_mysql']
    cr = db.cursor()
    v_sql = ''
    if config['db_id']!='':
        v_sql = '''insert into t_monitor_task_db_log (task_tag,server_id,db_id,total_connect,active_connect,db_available,create_date) 
                      values('{0}','{1}','{2}','{3}','{4}','{5}',now())
                '''.format(config['task_tag'], config['server_id'],config['db_id'],
                           config['total_connect'],config['active_connect'],config['db_available'])
    else:
        v_sql = '''insert into t_monitor_task_server_log
                      (task_tag,server_id,cpu_total_usage,cpu_core_usage,mem_usage,disk_usage,disk_read,disk_write,net_in,net_out,market_id,create_date) 
                        values('{0}','{1}','{2}','{3}','{4}','{5}','{6}','{7}','{8}','{9}','{10}',now())
                '''.format(config['task_tag'], config['server_id'],
                           config['cpu_total_usage'], config['cpu_core_usage'], config['mem_usage'],
                           config['disk_usage'], config['disk_read'], config['disk_write'],
                           config['net_in'], config['net_out'], config['market_id'])
    print('save_monitor_log=', v_sql)
    cr.execute(v_sql)
    db.commit()
    cr.close()
    return result


def save_sync_log_detail(config):
    result = {}
    result['code'] = 200
    result['msg'] = 'success'
    db=db_config()['db_mysql']
    cr=db.cursor()
    v_sql='''insert into t_db_sync_tasks_log_detail(sync_tag,create_date,sync_table,sync_amount,duration) 
              values('{0}','{1}','{2}','{3}','{4}')
          '''.format(config['sync_tag'],config['create_date'],config['sync_table'],config['sync_amount'],config['duration'])

    write_log(get_time())
    write_log(v_sql)
    cr.execute(v_sql)
    db.commit()
    cr.close()
    return result

def save_backup_total(config):
    result = {}
    result['code'] = 200
    result['msg'] = 'success'
    db=db_config()['db_mysql']
    cr=db.cursor()
    v_where = " where db_tag='{0}' and create_date='{1}'". \
               format(config['db_tag'], config['create_date'])
    if check_tab_exists('t_db_backup_total',v_where)==0:
        v_sql='''insert into t_db_backup_total(db_tag,create_date,bk_base,total_size,start_time,end_time,elaspsed_backup,elaspsed_gzip,status)
                  values('{0}','{1}','{2}','{3}','{4}','{5}','{6}','{7}','{8}')
              '''.format(config['db_tag'],config['create_date'],config['bk_base'],config['total_size'],
     config['start_time'],config['end_time'],config['elaspsed_backup'],
     config['elaspsed_gzip'],config['status'])

    else:
        v_sql='''update t_db_backup_total
                    set create_date = '{0}',
                        bk_base     = '{1}',
                        total_size  = '{2}',
                        start_time  = '{3}',
                        end_time    = '{4}',
                        elaspsed_backup = '{5}',
                        elaspsed_gzip = '{6}',
                        status = '{7}'
                  where db_tag = '{8}'
              '''.format(config['create_date'], config['bk_base'], config['total_size'],config['start_time'],
    config['end_time'], config['elaspsed_backup'],config['elaspsed_gzip'],
    config['status'],config['db_tag'])
    write_log(get_time())
    write_log(v_sql)
    cr.execute(v_sql)
    db.commit()
    cr.close()
    return result

def save_backup_detail(config):
    result = {}
    result['code'] = 200
    result['msg'] = 'success'
    db=db_config()['db_mysql']
    cr=db.cursor()
    v_where=" where db_tag='{0}' and db_name='{1}' and create_date='{2}'".\
               format(config['db_tag'] ,config['db_name'],config['create_date'])
    if check_tab_exists('t_db_backup_detail',v_where)==0:
        v_sql='''insert into t_db_backup_detail(
                      db_tag,create_date,db_name,bk_path,file_name,db_size,
                      start_time,end_time,elaspsed_backup,elaspsed_gzip,status,error)
                   values('{0}','{1}','{2}','{3}','{4}','{5}','{6}','{7}','{8}','{9}','{10}','{11}')
              '''.format(config['db_tag'],config['create_date'],config['db_name'],config['bk_path'],
                         config['file_name'],config['db_size'],config['start_time'],config['end_time'],
                         config['elaspsed_backup'],config['elaspsed_gzip'],config['status'],config['error'])

    else:
        v_sql='''update t_db_backup_detail
                    set bk_path     = '{0}',
                        file_name   = '{1}',
                        db_size     = '{2}',
                        start_time  = '{3}',
                        end_time    = '{4}',
                        elaspsed_backup = '{5}',
                        elaspsed_gzip   = '{6}',
                        status = '{7}',
                        error  = '{8}'
                    where db_tag = '{9}' and db_name='{10}' and create_date='{11}'
                    '''.format(config['bk_path'],config['file_name'],config['db_size'],
                    config['start_time'],config['end_time'], config['elaspsed_backup'],config['elaspsed_gzip'],
                    config['status'],config['error'],config['db_tag'],config['db_name'],config['create_date'])
    write_log(get_time())
    write_log(v_sql)
    cr.execute(v_sql)
    db.commit()
    cr.close()
    return result

def write_remote_crontab(v_tag):
    result = get_db_config(v_tag)
    if result['code']!=200:
       return result
    v_cmd   = '{0}/db_backup.sh {1} {2}'.format(result['msg']['script_path'],result['msg']['script_file'],v_tag)
    v_cron0 = '''echo -e "#{0}" >/tmp/conf'''.format(v_tag)
    v_cron1 = '''
                 crontab -l >> /tmp/conf && sed -i "/{0}/d" /tmp/conf && echo -e "\n#{1} tag={2}\n{3} {4} &>/dev/null &" >> /tmp/conf && crontab /tmp/conf       
              '''.format(v_tag,result['msg']['comments'],v_tag,result['msg']['run_time'],v_cmd)

    v_cron1_= '''
                 crontab -l > /tmp/conf && sed -i "/{0}/d" /tmp/conf && echo  -e "\n#{1} tag={2}\n#{3} {4} &>/dev/null &" >> /tmp/conf
              '''.format(v_tag, result['msg']['comments'], v_tag, result['msg']['run_time'], v_cmd)


    v_cron2 = '''sed -i '/^$/{N;/\\n$/D};' /tmp/conf'''
    v_cron3 = '''crontab /tmp/conf'''

    print(v_cron0)
    print(v_cron1)
    print(v_cron2)
    print(v_cron3)

    ssh = paramiko.SSHClient()
    print('Remote crontab update ....1')
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print('Remote crontab update ....2')
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    print('Remote crontab update ....')
    ssh.exec_command(v_cron0)

    if result['msg']['status'] == '1':
        ssh.exec_command(v_cron1)
    else:
        ssh.exec_command(v_cron1_)

    ssh.exec_command(v_cron2)
    ssh.exec_command(v_cron3)
    print('Remote crontab update complete!')
    ssh.close()
    return result

def run_remote_backup_task(v_tag):
    result = get_db_config(v_tag)
    if result['code']!=200:
       return result
    v_cmd   = 'nohup {0}/db_backup.sh {1} {2} &>/tmp/backup.log &>/dev/null &'.\
               format(result['msg']['script_path'],result['msg']['script_file'],v_tag)
    print(v_cmd)
    ssh = paramiko.SSHClient()
    print('Remote crontab update ....1')
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print('Remote crontab update ....2')
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    ssh.exec_command(v_cmd)
    print('Remote backup_task is running !')
    ssh.close()
    return result

def run_remote_sync_task(v_tag):
    result = get_db_sync_config(v_tag)
    if result['code']!=200:
       return result

    v_cmd   = 'nohup {0}/db_sync.sh {1} {2} &>/dev/null &'.format(result['msg']['script_path'], result['msg']['script_file'], v_tag)
    print(v_cmd)
    ssh = paramiko.SSHClient()
    print('Remote crontab update ....1')
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print('Remote crontab update ....2')
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    ssh.exec_command(v_cmd)
    print('Remote backup_task is running !')
    ssh.close()
    return result

def run_remote_datax_task(v_tag):
    result = get_datax_sync_config(v_tag)
    if result['code']!=200:
       return result
    v_cmd   = 'nohup {0}/datax_sync.sh {1} {2} &>/dev/null &'.format(result['msg']['script_path'], 'datax_sync.py', v_tag)
    print(v_cmd)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    ssh.exec_command(v_cmd)
    print('Remote datax_task is running !')
    ssh.close()
    return result

def run_remote_transfer_task(v_tag):
    result = get_db_transfer_config(v_tag)
    if result['code']!=200:
       return result

    v_cmd   = 'nohup {0}/db_transfer.sh {1} {2} &>/dev/null &'.format(result['msg']['script_path'], result['msg']['script_file'], v_tag)
    print(v_cmd)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    ssh.exec_command(v_cmd)
    print('Remote transfer task:{0} is running !'.format(v_tag))
    ssh.close()
    return result

def run_remote_archive_task(v_tag):
    result = get_db_archive_config(v_tag)
    if result['code']!=200:
       return result

    v_cmd   = 'nohup {0}/db_archive.sh {1} {2} &>/dev/null &'.format(result['msg']['script_path'], result['msg']['script_file'], v_tag)
    print(v_cmd)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    ssh.exec_command(v_cmd)
    print('Remote archive task:{0} is running !'.format(v_tag))
    ssh.close()
    return result

def stop_remote_backup_task(v_tag):
    result = get_db_config(v_tag)
    if result['code']!=200:
       return result

    v_cmd = """ps -ef | grep {0} |grep -v grep | awk '{print $2}'  | xargs kill -9""".format(v_tag)
    print(v_cmd)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    ssh.exec_command(v_cmd)
    print('Remote backup task:{0} is stopping !'.format(v_tag))
    ssh.close()
    return result

def stop_remote_sync_task(v_tag):
    result = get_db_sync_config(v_tag)
    if result['code']!=200:
       return result
    v_cmd1 = """ps -ef | grep {0} |grep -v grep | wc -l""".format(v_tag)
    v_cmd2 = """ps -ef | grep $$SYNC_TAG$$ |grep -v grep | awk '{print $2}'  | xargs kill -9
             """.replace('$$SYNC_TAG$$',v_tag)
    print(v_cmd1)
    print(v_cmd2)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)

    stdin, stdout, stderr = ssh.exec_command(v_cmd1)
    ret = stdout.read()
    ret = str(ret, encoding='utf-8').replace('\n','')
    print('stop_remote_sync_task->stdout=',ret,type(ret))
    if ret=='0':
       result['code'] = -1
       result['msg'] = '该任务未运行!'
       ssh.close()
       return result
    else:
       ssh.exec_command(v_cmd2)
       result['code'] = 200
       result['msg'] = '任务:{0}已停止!'.format(v_tag)
       ssh.close()
       return result

def stop_remote_transfer_task(v_tag):
    result = get_db_transfer_config(v_tag)
    if result['code']!=200:
       return result
    v_cmd1 = """ps -ef | grep $$TAG$$ |grep -v grep | awk '{print $2}'  | wc -l""".replace('$$TAG$$',v_tag)
    v_cmd2 = """ps -ef | grep $$TAG$$ |grep -v grep | awk '{print $2}'  | xargs kill -9""".replace('$$TAG$$',v_tag)
    print(v_cmd1)
    print(v_cmd2)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)

    stdin, stdout, stderr = ssh.exec_command(v_cmd1)
    ret = stdout.read()
    ret = str(ret, encoding='utf-8').replace('\n','')
    print('stop_remote_transfer_task->stdout=',ret)
    if ret == '0':
       result['code'] = -1
       result['msg'] = '该任务未运行!'
       ssh.close()
       return result
    else:
       ssh.exec_command(v_cmd2)
       result['code'] = 200
       result['msg'] = '任务:{0}已停止!'.format(v_tag)
       ssh.close()
       return result

def stop_remote_archive_task(v_tag):
    result = get_db_archive_config(v_tag)
    if result['code']!=200:
       return result
    v_cmd1 = """ps -ef | grep $$TAG$$ |grep -v grep | awk '{print $2}'  | wc -l""".replace('$$TAG$$',v_tag)
    v_cmd2 = """ps -ef | grep $$TAG$$ |grep -v grep | awk '{print $2}'  | xargs kill -9""".replace('$$TAG$$',v_tag)
    print(v_cmd1)
    print(v_cmd2)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)

    stdin, stdout, stderr = ssh.exec_command(v_cmd1)
    ret = stdout.read()
    ret = str(ret, encoding='utf-8').replace('\n','')
    print('stop_remote_archive_task->stdout=',ret)
    if ret == '0':
       result['code'] = -1
       result['msg'] = '该任务未运行!'
       ssh.close()
       return result
    else:
       ssh.exec_command(v_cmd2)
       result['code'] = 200
       result['msg'] = '任务:{0}已停止!'.format(v_tag)
       ssh.close()
       return result


def stop_datax_sync_task(v_tag):
    result = get_datax_sync_config(v_tag)
    if result['code']!=200:
       return result
    v_cmd1 = """ps -ef | grep $$TAG$$ |grep -v grep | wc -l""".replace('$$TAG$$',v_tag)
    v_cmd2 = """ps -ef | grep $$TAG$$ |grep -v grep | awk '{print $2}'  | xargs kill -9""".replace('$$TAG$$',v_tag)
    print(v_cmd1)
    print(v_cmd2)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    config = db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip']  , port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)

    stdin, stdout, stderr = ssh.exec_command(v_cmd1)
    ret = stdout.read()
    ret = str(ret, encoding='utf-8').replace('\n','')
    print('stop_datax_sync_task->stdout=',ret)
    if ret == '0':
       result['code'] = -1
       result['msg'] = '该任务未运行!'
       ssh.close()
       return result
    else:
       ssh.exec_command(v_cmd2)
       result['code'] = 200
       result['msg'] = '任务:{0}已停止!'.format(v_tag)
       ssh.close()
       return result

def write_remote_crontab_sync(v_tag):
    result = get_db_sync_config(v_tag)
    if result['code']!=200:
       return result

    v_cmd = '{0}/db_sync.sh {1} {2}'.format(result['msg']['script_path'],result['msg']['script_file'], v_tag)

    v_cron = '''
               crontab -l > /tmp/conf && sed -i "/{0}/d" /tmp/conf && echo  -e "\n#{1} tag={2}\n{3} {4} &>/dev/null &" >> /tmp/conf
             '''.format(v_tag,result['msg']['comments'],v_tag,result['msg']['run_time'],v_cmd)

    v_cron_ = '''
                crontab -l > /tmp/conf && sed -i "/{0}/d" /tmp/conf && echo  -e "\n#{1} tag={2}\n#{3} {4} &>/dev/null &" >> /tmp/conf
             '''.format(v_tag, result['msg']['comments'], v_tag, result['msg']['run_time'], v_cmd)


    v_cron2 ='''sed -i '/^$/{N;/\\n$/D};' /tmp/conf'''
    v_cron3 ='''crontab /tmp/conf'''

    # Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('write_remote_crontab_sync ->v_password=', v_password)

    #connect server
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'], port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    #exec v_cron
    if result['msg']['status']=='1':
       ssh.exec_command(v_cron)
    else:
       ssh.exec_command(v_cron_)

    ssh.exec_command(v_cron2)
    ssh.exec_command(v_cron3)
    print('Remote crontab update complete!')
    ssh.close()
    return result

def write_remote_crontab_monitor(v_tag):
    result = get_db_monitor_config(v_tag)
    if result['code']!=200:
       return result

    v_cmd = '{0}/db_monitor.sh {1} {2}'.format(result['msg']['script_path'],result['msg']['script_file'], v_tag)

    v_cron = '''
               crontab -l > /tmp/conf && sed -i "/{0}/d" /tmp/conf && echo  -e "\n#{1} tag={2}\n{3} {4} &>/dev/null &" >> /tmp/conf
             '''.format(v_tag,result['msg']['comments'],v_tag,result['msg']['run_time'],v_cmd)

    v_cron_ = '''
                crontab -l > /tmp/conf && sed -i "/{0}/d" /tmp/conf && echo  -e "\n#{1} tag={2}\n#{3} {4} &>/dev/null &" >> /tmp/conf
             '''.format(v_tag, result['msg']['comments'], v_tag, result['msg']['run_time'], v_cmd)


    v_cron2 ='''sed -i '/^$/{N;/\\n$/D};' /tmp/conf'''
    v_cron3 ='''crontab /tmp/conf'''

    # Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('write_remote_crontab_sync ->v_password=', v_password)

    #connect server
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'], port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    #exec v_cron
    if result['msg']['status']=='1':
       ssh.exec_command(v_cron)
    else:
       ssh.exec_command(v_cron_)

    ssh.exec_command(v_cron2)
    ssh.exec_command(v_cron3)
    print('Remote crontab update complete!')
    ssh.close()
    return result



def write_datax_remote_crontab_sync(v_tag):
    result = get_datax_sync_config(v_tag)
    if result['code']!=200:
       return result

    v_cmd   = '{0}/datax_sync.sh {1} {2}'.format(result['msg']['script_path'],'datax_sync.py', v_tag)

    v_cron  = '''
                crontab -l > /tmp/conf && sed -i "/{0}/d" /tmp/conf && echo  -e "\n#{1} tag={2}\n{3} {4} &>/dev/null &" >> /tmp/conf
              '''.format(v_tag,result['msg']['comments'],v_tag,result['msg']['run_time'],v_cmd)

    v_cron_ = '''
                crontab -l > /tmp/conf && sed -i "/{0}/d" /tmp/conf && echo  -e "\n#{1} tag={2}\n#{3} {4} &>/dev/null &" >> /tmp/conf
              '''.format(v_tag, result['msg']['comments'], v_tag, result['msg']['run_time'], v_cmd)


    v_cron2 ='''sed -i '/^$/{N;/\\n$/D};' /tmp/conf'''
    v_cron3 ='''crontab /tmp/conf'''

    # Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('write_remote_crontab_sync ->v_password=', v_password)

    #connect server
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'], port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    #exec v_cron
    if result['msg']['status']=='1':
       ssh.exec_command(v_cron)
    else:
       ssh.exec_command(v_cron_)

    ssh.exec_command(v_cron2)
    ssh.exec_command(v_cron3)
    print('Remote write_datax_remote_crontab_sync update complete!')
    ssh.close()
    return result

def transfer_remote_file(v_tag):
    result  = get_db_config(v_tag)
    print('transfer_remote_file=',result)
    if result['code']!=200:
       return result

    config=db_config()
    print('config[db_mysql=',config['db_mysql'])
    print(result['msg']['server_pass'],result['msg']['server_user'])
    v_password=aes_decrypt(config['db_mysql'],result['msg']['server_pass'],result['msg']['server_user'])
    print('transfer_remote_file ->v_password=',v_password)
    transport = paramiko.Transport((result['msg']['server_ip'], int(result['msg']['server_port'])))
    transport.connect(username=result['msg']['server_user'], password=v_password)
    sftp = paramiko.SFTPClient.from_transport(transport)

    #replace script file
    templete_file = './templete/{0}'.format(result['msg']['script_file'])
    local_file    = './script/{0}'.format(result['msg']['script_file'])
    remote_file   = '{0}/{1}'.format(result['msg']['script_path'], result['msg']['script_file'])
    print('templete_file=', templete_file)
    print('local_file=', local_file)
    print('remote_file=', remote_file)
    os.system('cp -f {0} {1}'.format(templete_file, local_file))
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$API_SERVER$$', result['msg']['api_server']))

    #send .py file
    local_file = './script/{0}'.format(result['msg']['script_file'])
    remote_file = '{0}/{1}'.format(result['msg']['script_path'],result['msg']['script_file'])
    sftp.put(localpath=local_file, remotepath=remote_file)
    print('Script:{0} send to {1} ok.'.format(local_file, remote_file))

    #send .sh file
    templete_file = './templete/db_backup.sh'
    local_file    = './script/db_backup.sh'
    remote_file   = '{0}/db_backup.sh'.format(result['msg']['script_path'])

    os.system('cp -f {0} {1}'.format(templete_file,local_file))
    print('templete_file=',templete_file)
    print('local_file=',local_file)
    print('remote_file=',remote_file)
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$PYTHON3_HOME$$',result['msg']['python3_home']).
                       replace('$$SCRIPT_PATH$$',result['msg']['script_path']))
    sftp.put(localpath=local_file, remotepath=remote_file)
    print('Script:{0} send to {1} ok.'.format(local_file,remote_file))
    transport.close()
    return result

def transfer_remote_file_sync(v_tag):
    print('transfer_remote_file_sync!')
    result = {}
    result['code'] = 200
    result['msg']  = ''
    result = get_db_sync_config(v_tag)
    print('transfer_remote_file_sync=',result)
    if result['code']!=200:
       return result

    #Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('transfer_remote_file_sync ->v_password=', v_password)

    transport = paramiko.Transport((result['msg']['server_ip'], int(result['msg']['server_port'])))
    transport.connect(username=result['msg']['server_user'], password=v_password)
    sftp = paramiko.SFTPClient.from_transport(transport)

    #replace script file
    templete_file = './templete/{0}'.format(result['msg']['script_file'])
    local_file    = './script/{0}'.format(result['msg']['script_file'])
    remote_file   = '{0}/{1}'.format(result['msg']['script_path'], result['msg']['script_file'])
    os.system('cp -f {0} {1}'.format(templete_file, local_file))
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$API_SERVER$$', result['msg']['api_server']))

    #create sync directory
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'], port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    ssh.exec_command('mkdir -p {0}'.format(result['msg']['script_path']))
    print("remote sync directory '{0}' created!".format(result['msg']['script_path']))

    #send .py file
    local_file  = './script/{0}'.format(result['msg']['script_file'])
    remote_file = '{0}/{1}'.format(result['msg']['script_path'],result['msg']['script_file'])
    print('transfer_remote_file_sync'+'$'+local_file+'$'+remote_file)
    sftp.put(localpath=local_file, remotepath=remote_file)
    print('Script:{0} send to {1} ok.'.format(local_file, remote_file))

    #send mysql_sync.sh file
    templete_file = './templete/db_sync.sh'
    local_file    = './script/db_sync.sh'
    remote_file   = '{0}/db_sync.sh'.format(result['msg']['script_path'])
    os.system('cp -f {0} {1}'.format(templete_file, local_file))
    print('templete_file=',templete_file)
    print('local_file=',local_file)
    print('remote_file=',remote_file)
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$PYTHON3_HOME$$', result['msg']['python3_home']).
                       replace('$$SCRIPT_PATH$$' , result['msg']['script_path']))
    sftp.put(localpath=local_file, remotepath=remote_file)
    write_log('Script:{0} send to {1} ok.'.format(local_file, remote_file))
    transport.close()
    ssh.close()
    return result

def transfer_remote_file_transfer(v_tag):
    print('transfer_remote_file_sync!')
    result = {}
    result['code'] = 200
    result['msg']  = ''
    result = get_db_transfer_config(v_tag)
    print('transfer_remote_file_transfer=',result)
    if result['code']!=200:
       return result

    #Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('transfer_remote_file_sync ->v_password=', v_password)

    transport = paramiko.Transport((result['msg']['server_ip'], int(result['msg']['server_port'])))
    transport.connect(username=result['msg']['server_user'], password=v_password)
    sftp = paramiko.SFTPClient.from_transport(transport)

    #replace script file
    templete_file = './templete/{0}'.format(result['msg']['script_file'])
    local_file    = './script/{0}'.format(result['msg']['script_file'])
    os.system('cp -f {0} {1}'.format(templete_file, local_file))
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$API_SERVER$$', result['msg']['api_server']))

    #create sync directory
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'], port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    ssh.exec_command('mkdir -p {0}'.format(result['msg']['script_path']))
    print("remote sync directory '{0}' created!".format(result['msg']['script_path']))

    #send .py file
    local_file  = './script/{0}'.format(result['msg']['script_file'])
    remote_file = '{0}/{1}'.format(result['msg']['script_path'],result['msg']['script_file'])
    print('transfer_remote_file_sync'+'$'+local_file+'$'+remote_file)
    sftp.put(localpath=local_file, remotepath=remote_file)
    print('Script:{0} send to {1} ok.'.format(local_file, remote_file))

    #send mysql_transfer.sh file
    templete_file = './templete/db_transfer.sh'
    local_file    = './script/db_transfer.sh'
    remote_file   = '{0}/db_transfer.sh'.format(result['msg']['script_path'])
    os.system('cp -f {0} {1}'.format(templete_file, local_file))
    print('templete_file=',templete_file)
    print('local_file=',local_file)
    print('remote_file=',remote_file)
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$PYTHON3_HOME$$', result['msg']['python3_home']).
                       replace('$$SCRIPT_PATH$$' , result['msg']['script_path']))
    sftp.put(localpath=local_file, remotepath=remote_file)
    write_log('Script:{0} send to {1} ok.'.format(local_file, remote_file))
    transport.close()
    ssh.close()
    return result

def transfer_remote_file_archive(v_tag):
    print('transfer_remote_file_sync!')
    result = {}
    result['code'] = 200
    result['msg']  = ''
    result = get_db_archive_config(v_tag)
    print('transfer_remote_file_archive=',result)
    if result['code']!=200:
       return result

    #Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('transfer_remote_file_archive ->v_password=', v_password)

    transport = paramiko.Transport((result['msg']['server_ip'], int(result['msg']['server_port'])))
    transport.connect(username=result['msg']['server_user'], password=v_password)
    sftp = paramiko.SFTPClient.from_transport(transport)

    #replace script file
    templete_file = './templete/{0}'.format(result['msg']['script_file'])
    local_file    = './script/{0}'.format(result['msg']['script_file'])
    os.system('cp -f {0} {1}'.format(templete_file, local_file))
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$API_SERVER$$', result['msg']['api_server']))

    #create sync directory
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'], port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    ssh.exec_command('mkdir -p {0}'.format(result['msg']['script_path']))
    print("remote sync directory '{0}' created!".format(result['msg']['script_path']))

    #send .py file
    local_file  = './script/{0}'.format(result['msg']['script_file'])
    remote_file = '{0}/{1}'.format(result['msg']['script_path'],result['msg']['script_file'])
    print('transfer_remote_file_archive'+'$'+local_file+'$'+remote_file)
    sftp.put(localpath=local_file, remotepath=remote_file)
    print('Script:{0} send to {1} ok.'.format(local_file, remote_file))

    #send mysql_transfer.sh file
    templete_file = './templete/db_archive.sh'
    local_file    = './script/db_archive.sh'
    remote_file   = '{0}/db_archive.sh'.format(result['msg']['script_path'])
    os.system('cp -f {0} {1}'.format(templete_file, local_file))
    print('templete_file=',templete_file)
    print('local_file=',local_file)
    print('remote_file=',remote_file)
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$PYTHON3_HOME$$', result['msg']['python3_home']).
                       replace('$$SCRIPT_PATH$$' , result['msg']['script_path']))
    sftp.put(localpath=local_file, remotepath=remote_file)
    write_log('Script:{0} send to {1} ok.'.format(local_file, remote_file))
    transport.close()
    ssh.close()
    return result


def transfer_remote_file_monitor(v_tag):
    print('transfer_remote_file_monitor!')
    result = {}
    result['code'] = 200
    result['msg']  = ''
    result = get_db_monitor_config(v_tag)
    print('transfer_remote_file_monitor=',result)
    if result['code']!=200:
       return result

    #Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('transfer_remote_file_monitor ->v_password=', v_password)

    transport = paramiko.Transport((result['msg']['server_ip'], int(result['msg']['server_port'])))
    transport.connect(username=result['msg']['server_user'], password=v_password)
    sftp = paramiko.SFTPClient.from_transport(transport)

    #replace script file
    templete_file = './templete/{0}'.format(result['msg']['script_file'])
    local_file    = './script/{0}'.format(result['msg']['script_file'])
    os.system('cp -f {0} {1}'.format(templete_file, local_file))
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$API_SERVER$$', result['msg']['api_server']))

    #create sync directory
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'], port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    ssh.exec_command('mkdir -p {0}'.format(result['msg']['script_path']))
    print("remote sync directory '{0}' created!".format(result['msg']['script_path']))

    #send .py file
    local_file  = './script/{0}'.format(result['msg']['script_file'])
    remote_file = '{0}/{1}'.format(result['msg']['script_path'],result['msg']['script_file'])
    print('transfer_remote_file_monitor'+'$'+local_file+'$'+remote_file)
    sftp.put(localpath=local_file, remotepath=remote_file)
    print('Script:{0} send to {1} ok.'.format(local_file, remote_file))

    #send mysql_transfer.sh file
    templete_file = './templete/db_monitor.sh'
    local_file    = './script/db_monitor.sh'
    remote_file   = '{0}/db_monitor.sh'.format(result['msg']['script_path'])
    os.system('cp -f {0} {1}'.format(templete_file, local_file))
    print('templete_file=',templete_file)
    print('local_file=',local_file)
    print('remote_file=',remote_file)
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$PYTHON3_HOME$$', result['msg']['python3_home']).
                       replace('$$SCRIPT_PATH$$' , result['msg']['script_path']))
    sftp.put(localpath=local_file, remotepath=remote_file)
    write_log('Script:{0} send to {1} ok.'.format(local_file, remote_file))
    transport.close()
    ssh.close()
    return result


def query_datax_by_id(sync_id):
    db  = db_config()['db_mysql']
    print('db=',db)
    cr  = db.cursor()
    sql = """SELECT
                 a.sync_tag,
                 a.server_id,
                 a.sour_db_id,
                 a.sync_schema,
                 a.sync_table,
                 a.sync_incr_col,
                 e.user,
                 e.password,
                 a.sync_columns,
                 a.sync_table,
                 CONCAT(e.ip,':',e.port,'/',a.sync_schema) AS mysql_url,
                 a.zk_hosts,
                 a.sync_hbase_table,
                 a.sync_hbase_rowkey,
                 a.sync_hbase_rowkey_sour,
                 a.sync_hbase_rowkey_separator,
                 a.sync_hbase_columns,
                 a.sync_incr_where,
                 a.sync_ywlx,
                 a.sync_type,
                 a.script_path,
                 a.run_time,
                 a.comments,
                 a.datax_home,
                 a.sync_time_type,
                 a.sync_gap,
                 a.api_server,
                 a.status,
                 a.python3_home
            FROM t_datax_sync_config a,t_server b ,t_dmmx c,t_dmmx d,t_db_source e
            WHERE a.server_id=b.id AND b.status='1' 
            AND a.sour_db_id=e.id
            AND c.dm='08' AND d.dm='09'
            AND a.sync_ywlx=c.dmm
            AND a.sync_type=d.dmm
            AND a.id='{0}'
         """.format(sync_id)
    print(sql)
    cr.execute(sql)
    rs=cr.fetchone()
    cr.close()
    db.commit()
    return rs

def get_mysql_columns(p_sync):
    v = '''"{0}",'''.format(p_sync['sync_hbase_rowkey_sour'])
    for i in p_sync['sync_columns'].split(','):
        v = v + '''"{}",'''.format(i)
    print('get_mysql_columns=', v)
    return v[0:-1]

def process_templete(p_sync_id,p_templete):
    db = db_config()['db_mysql']
    v_templete = p_templete
    p_sync = query_datax_by_id(p_sync_id)
    v_pass = aes_decrypt(db,p_sync['password'],p_sync['user'])
    print('process_templete->p_sync=',p_sync)
    print('process_templete->p_templete=',p_templete)
    #replace full templete
    v_templete['full'] = v_templete['full'].replace('$$USERNAME$$',p_sync['user'])
    v_templete['full'] = v_templete['full'].replace('$$PASSWORD$$',v_pass)
    v_templete['full'] = v_templete['full'].replace('$$MYSQL_COLUMN_NAMES$$', get_mysql_columns(p_sync))
    v_templete['full'] = v_templete['full'].replace('$$MYSQL_TABLE_NAME$$', p_sync['sync_table'])
    v_templete['full'] = v_templete['full'].replace('$$MYSQL_URL$$', p_sync['mysql_url'])
    v_templete['full'] = v_templete['full'].replace('$$USERNAME$$', p_sync['user'])
    v_templete['full'] = v_templete['full'].replace('$$ZK_HOSTS', p_sync['zk_hosts'])
    v_templete['full'] = v_templete['full'].replace('$$HBASE_TABLE_NAME$$', p_sync['sync_hbase_table'])
    v_templete['full'] = v_templete['full'].replace('$$HBASE_ROWKEY$$', p_sync['sync_hbase_rowkey'])
    v_templete['full'] = v_templete['full'].replace('$$HBASE_COLUMN_NAMES$$', p_sync['sync_hbase_columns'])
    #replacre incr templete
    v_templete['incr'] = v_templete['incr'].replace('$$USERNAME$$', p_sync['user'])
    v_templete['incr'] = v_templete['incr'].replace('$$PASSWORD$$', v_pass)
    v_templete['incr'] = v_templete['incr'].replace('$$MYSQL_COLUMN_NAMES$$', get_mysql_columns(p_sync))
    v_templete['incr'] = v_templete['incr'].replace('$$MYSQL_TABLE_NAME$$', p_sync['sync_table'])
    v_templete['incr'] = v_templete['incr'].replace('$$MYSQL_URL$$', p_sync['mysql_url'])
    v_templete['incr'] = v_templete['incr'].replace('$$USERNAME$$', p_sync['user'])
    v_templete['incr'] = v_templete['incr'].replace('$$ZK_HOSTS', p_sync['zk_hosts'])
    v_templete['incr'] = v_templete['incr'].replace('$$HBASE_TABLE_NAME$$', p_sync['sync_hbase_table'])
    v_templete['incr'] = v_templete['incr'].replace('$$HBASE_ROWKEY$$', p_sync['sync_hbase_rowkey'])
    v_templete['incr'] = v_templete['incr'].replace('$$HBASE_COLUMN_NAMES$$', p_sync['sync_hbase_columns'])
    v_templete['incr'] = v_templete['incr'].replace('$$MYSQL_WHERE$$', p_sync['sync_incr_where'])
    print('process_templete->v_templete=', v_templete)
    return v_templete

def query_datax_sync_dataxTemplete(sync_id):
    templete   = {}
    db         = db_config2()['db_mysql']
    cr         = db.cursor()
    sql_full   = 'select contents from t_templete where templete_id=1'
    print(sql_full)
    cr.execute(sql_full)
    rs=cr.fetchone()
    templete['full']   = rs[0]
    sql_incr = 'select contents from t_templete where templete_id=2'
    print(sql_incr)
    cr.execute(sql_incr)
    rs = cr.fetchone()
    templete['incr']=rs[0]
    cr.close()
    db.commit()
    v_templete=process_templete(sync_id,templete)
    print('query_datax_sync_dataxTemplete=',v_templete)
    return v_templete

def get_datax_sync_templete(id):
    try:
        result = {}
        result['code'] = 200
        templete       = query_datax_sync_dataxTemplete(id)
        result['msg']  = templete
        return result
    except Exception as e:
        result = {}
        result['code'] = -1
        result['msg']  = str(e)
        return result

def write_datax_sync_TempleteFile(sync_id,):

    sync_tag = query_datax_by_id(sync_id)['sync_tag']

    #获取模板内容至templete字典中
    templete = query_datax_sync_dataxTemplete(sync_id)

    #生成全量json文件
    v_datax_full_file = './datax/{0}_full.json'.format(sync_tag)
    with open(v_datax_full_file, 'w') as f:
        f.write(templete['full'])

    #生成增量json文件
    v_datax_incr_file = './datax/{0}_incr.json'.format(sync_tag)
    with open(v_datax_incr_file, 'w') as f:
        f.write(templete['incr'])

    return  v_datax_full_file, v_datax_incr_file

def transfer_datax_remote_file_sync(v_tag):
    print('transfer_remote_file_sync!')
    result = {}
    result['code'] = 200
    result['msg']  = ''
    result = get_datax_sync_config(v_tag)
    print('transfer_datax_remote_file_sync=',result)
    if result['code']!=200:
       return result

    #Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('transfer_remote_file_sync ->v_password=', v_password)

    transport = paramiko.Transport((result['msg']['server_ip'], int(result['msg']['server_port'])))
    transport.connect(username=result['msg']['server_user'], password=v_password)
    sftp = paramiko.SFTPClient.from_transport(transport)

    #create sync directory
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'], port=int(result['msg']['server_port']),
                username=result['msg']['server_user'], password=v_password)
    ssh.exec_command('mkdir -p {0}'.format(result['msg']['script_path']))
    print("remote sync directory '{0}' created!".format(result['msg']['script_path']))

    # write json file
    f_datax_full,f_datax_incr = write_datax_sync_TempleteFile(result['msg']['id'])
    print('files=',f_datax_full,f_datax_incr)

    # send full json file
    # ---------------------------------------------------------------------------------------------------
    local_file  = '{0}'.format(f_datax_full)
    remote_file = '{0}/{1}'.format(result['msg']['script_path'], f_datax_full.split('/')[-1])
    print('transfer_datax_remote_file_sync full file!   ',local_file,remote_file)
    sftp.put(localpath=local_file, remotepath=remote_file)
    print('Script:{0} send to {1} ok.'.format(local_file, remote_file))

    # send incr json file
    local_file  = '{0}'.format(f_datax_incr)
    remote_file = '{0}/{1}'.format(result['msg']['script_path'], f_datax_incr.split('/')[-1])
    print('transfer_datax_remote_file_sync incr file!',local_file,remote_file)
    sftp.put(localpath=local_file, remotepath=remote_file)
    print('Script:{0} send to {1} ok.'.format(local_file, remote_file))

    # replace datax_sync.py variables
    templete_file = './templete/datax_sync.py'
    local_file  = './datax/datax_sync.py'
    remote_file = '{0}/datax_sync.py'.format(result['msg']['script_path'])
    print('replace datax_sync.py=', templete_file, local_file, remote_file)
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$API_SERVER$$', result['msg']['api_server']))

    # send datax_sync.py file
    local_file  = './datax/datax_sync.py'
    remote_file = '{0}/{1}'.format(result['msg']['script_path'],'datax_sync.py')
    print('transfer_remote_file_sync'+'$'+local_file+'$'+remote_file.split('/')[-1])
    sftp.put(localpath=local_file, remotepath=remote_file)
    print('Script:{0} send to {1} ok.'.format(local_file, remote_file))


    # replace datax_sync.sh variables
    templete_file = './templete/datax_sync.sh'
    local_file    = './datax/datax_sync.sh'
    remote_file   = '{0}/datax_sync.sh'.format(result['msg']['script_path'])
    print('replace datax_sync.sh=', templete_file,local_file,remote_file)
    with open(local_file, 'w') as obj_file:
        obj_file.write(get_file_contents(templete_file).
                       replace('$$PYTHON3_HOME$$', result['msg']['python3_home']).
                       replace('$$SCRIPT_PATH$$', result['msg']['script_path']))

    # send datax_sync.sh file
    local_file    = './datax/datax_sync.sh'
    remote_file   = '{0}/datax_sync.sh'.format(result['msg']['script_path'])
    sftp.put(localpath=local_file, remotepath=remote_file)
    sftp.put(localpath='./datax/repstr.sh', remotepath=result['msg']['script_path']+'/repstr.sh')
    write_log('Script:{0} send to {1} ok.'.format(local_file, remote_file))
    transport.close()
    ssh.close()
    return result

def run_remote_cmd(v_tag):
    result = get_db_config(v_tag)
    if result['code'] != 200:
        return result
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    config=db_config()
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    ssh.connect(hostname=result['msg']['server_ip'], port=int(result['msg']['server_port']),
                username=result['msg']['server_user'],password=v_password)
    remote_file1 = '{0}/{1}'.format(result['msg']['script_path'], result['msg']['script_file'])
    remote_file2 = '{0}/{1}'.format(result['msg']['script_path'], 'db_backup.sh')
    remote_cmd1  = 'mkdir -p {0}'.format(result['msg']['script_path']+'/config')
    ssh.exec_command('chmod +x {0}'.format(remote_file1))
    ssh.exec_command('chmod +x {0}'.format(remote_file2))
    ssh.exec_command(remote_cmd1)
    ssh.close()
    return result

def run_remote_cmd_sync(v_tag):
    # Init dict
    result = {}
    result['code'] = 200
    result['msg'] = ''
    print('run_remote_cmd_sync!')
    result = get_db_sync_config(v_tag)
    if result['code'] != 200:
        return result

    # Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('run_remote_cmd_sync ->v_password=', v_password)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'] ,port=int(result['msg']['server_port']),
                username=result['msg']['server_user'],password=v_password)
    print('run_remote_cmd_sync! connect!')
    remote_file1 = '{0}/{1}'.format(result['msg']['script_path'], result['msg']['script_file'])
    remote_file2 = '{0}/{1}'.format(result['msg']['script_path'], 'db_sync.sh')
    remote_cmd1  = 'mkdir -p {0}'.format(result['msg']['script_path'] + '/config')
    ssh.exec_command('chmod +x {0}'.format(remote_file1))
    ssh.exec_command('chmod +x {0}'.format(remote_file2))
    ssh.exec_command(remote_cmd1)
    print('run_remote_cmd_sync! exec_command!')
    ssh.close()
    return result

def run_remote_cmd_transfer(v_tag):
    # Init dict
    result = {}
    result['code'] = 200
    result['msg'] = ''
    print('run_remote_cmd_sync!')
    result = get_db_transfer_config(v_tag)
    if result['code'] != 200:
        return result

    # Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('run_remote_cmd_transfer ->v_password=', v_password)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'] ,port=int(result['msg']['server_port']),
                username=result['msg']['server_user'],password=v_password)
    print('run_remote_cmd_transfer! connect!')
    remote_file1 = '{0}/{1}'.format(result['msg']['script_path'], result['msg']['script_file'])
    remote_file2 = '{0}/{1}'.format(result['msg']['script_path'], 'db_transfer.sh')
    ssh.exec_command('chmod +x {0}'.format(remote_file1))
    ssh.exec_command('chmod +x {0}'.format(remote_file2))
    print('run_remote_cmd_transfer! exec_command!')
    ssh.close()
    return result

def run_remote_cmd_archive(v_tag):
    # Init dict
    result = {}
    result['code'] = 200
    result['msg'] = ''
    result = get_db_archive_config(v_tag)
    if result['code'] != 200:
        return result

    # Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('run_remote_cmd_archive ->v_password=', v_password)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'] ,port=int(result['msg']['server_port']),
                username=result['msg']['server_user'],password=v_password)
    print('run_remote_cmd_archive! connect!')
    remote_file1 = '{0}/{1}'.format(result['msg']['script_path'], result['msg']['script_file'])
    remote_file2 = '{0}/{1}'.format(result['msg']['script_path'], 'db_archive.sh')
    ssh.exec_command('chmod +x {0}'.format(remote_file1))
    ssh.exec_command('chmod +x {0}'.format(remote_file2))
    print('run_remote_cmd_archive! exec_command!')
    ssh.close()
    return result

def run_remote_cmd_monitor(v_tag):
    # Init dict
    result = {}
    result['code'] = 200
    result['msg'] = ''
    result = get_db_monitor_config(v_tag)
    if result['code'] != 200:
        return result

    # Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('run_remote_cmd_monitor ->v_password=', v_password)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'] ,port=int(result['msg']['server_port']),
                username=result['msg']['server_user'],password=v_password)
    print('run_remote_cmd_archive! connect!')
    remote_file1 = '{0}/{1}'.format(result['msg']['script_path'], result['msg']['script_file'])
    remote_file2 = '{0}/{1}'.format(result['msg']['script_path'], 'db_monitor.sh')
    ssh.exec_command('chmod +x {0}'.format(remote_file1))
    ssh.exec_command('chmod +x {0}'.format(remote_file2))
    print('run_remote_cmd_monitor! exec_command!')
    ssh.close()
    return result

def run_datax_remote_cmd_sync(v_tag):
    # Init dict
    result = {}
    result['code'] = 200
    result['msg'] = ''
    print('run_datax_remote_cmd_sync!')
    result = get_datax_sync_config(v_tag)
    if result['code'] != 200:
        return result

    # Decryption password
    config = db_config()
    print('config[db_mysql=', config['db_mysql'])
    print(result['msg']['server_pass'], result['msg']['server_user'])
    v_password = aes_decrypt(config['db_mysql'], result['msg']['server_pass'], result['msg']['server_user'])
    print('run_remote_cmd_sync ->v_password=', v_password)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=result['msg']['server_ip'] ,port=int(result['msg']['server_port']),
                username=result['msg']['server_user'],password=v_password)
    print('run_datax_remote_cmd_sync! connect!')

    #为.sh,.py文件授执行权限
    ssh.exec_command('chmod +x {0}'.format(result['msg']['script_path']+'/repstr.sh'))
    ssh.exec_command('chmod +x {0}'.format(result['msg']['script_path']+'/datax_sync.sh'))
    ssh.exec_command('chmod +x {0}'.format(result['msg']['script_path']+'/datax_sync.py'))

    #替换datax配置文件中^M字符
    print('Replace ^M 字符...{0}'.format(result['msg']['script_path'],result['msg']['script_path']+'/'+v_tag+'_full.json'))
    ssh.exec_command('{0}/repstr.sh {1}'.format(result['msg']['script_path'],result['msg']['script_path']+'/'+v_tag+'_full.json'))
    ssh.exec_command('{0}/repstr.sh {1}'.format(result['msg']['script_path'],result['msg']['script_path']+'/'+v_tag+'_incr.json'))

    print('run_remote_cmd_sync! exec_command!')
    ssh.close()
    return result

class read_config_backup(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag     = self.get_argument("tag")
            result    = get_db_config(v_tag)
            v_json    = json.dumps(result)
            print("{0} dbops api interface /read_config_backup success!".format(get_time()))
            print("入口参数：\n\t{0}".format(v_tag))
            print("出口参数：")
            print(result['msg'] )
            self.write(v_json)
        except Exception as e:
            print(str(e))

class read_db_decrypt(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_pass     = self.get_argument("password")
            v_key      = self.get_argument("key")
            config     = db_config()
            db         = config['db_mysql']
            v_new_pass = aes_decrypt(db,v_pass,v_key)
            result = {}
            result['code'] = 200
            result['msg']  = v_new_pass
            v_json = json.dumps(result)
            print("{0} dbops api interface /read_db_decrypt success!".format(get_time()))
            print(result['msg'])
            self.write(v_json)
        except Exception as e:
            print(str(e))

class write_backup_status(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            rs=get_task_tags()
            for i in range(len(rs)):
                print(rs[i]['db_tag'])
                result = update_backup_status(rs[i]['db_tag'])
                print(rs[i]['db_tag'],result)
            print("{0} dbops api interface /read_backup_status success!".format(get_time()))
            self.write('update_backup_status')
        except Exception as e:
            print(str(e))

class write_backup_total(tornado.web.RequestHandler):
    def post(self):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        v_tag   = self.get_argument("tag")
        config  = json.loads(v_tag)
        result  = save_backup_total(config)
        v_json  = json.dumps(result)
        write_log("{0} dbops api interface /write_backup_total success!".format(get_time()))
        write_log("入口参数:")
        print_dict(config)
        write_log("出口参数：")
        print_dict(result)
        self.write(v_json)

class write_backup_detail(tornado.web.RequestHandler):
    def post(self):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        v_tag   = self.get_argument("tag")
        config  = json.loads(v_tag)
        result  = save_backup_detail(config)
        v_json  = json.dumps(result)
        write_log("{0} dbops api interface /write_backup_detail success!".format(get_time()))
        write_log("入口参数:")
        print_dict(config)
        write_log("出口参数：")
        print_dict(result)
        self.write(v_json)

class read_config_sync(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            result  = get_db_sync_config(v_tag)
            v_json  = json.dumps(result)
            write_log("{0} dbops api interface /read_config_sync success!".format(get_time()))
            write_log("入口参数：\n\t{0}".format(v_tag))
            write_log("出口参数：")
            if result['code']==200:
                print_dict(result['msg'])
            self.write(v_json)
        except Exception as e:
            write_log(str(e))
            result['code'] = -1
            result['msg'] = str(e)
            self.write(v_json)

class read_config_transfer(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            result  = get_db_transfer_config(v_tag)
            v_json  = json.dumps(result)
            write_log("{0} dbops api interface /read_config_transfer success!".format(get_time()))
            write_log("入口参数：\n\t{0}".format(v_tag))
            write_log("出口参数：")
            if result['code']==200:
                print_dict(result['msg'])
            self.write(v_json)
        except Exception as e:
            write_log(str(e))
            result['code'] = -1
            result['msg'] = str(e)
            self.write(v_json)

class read_config_archive(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            result  = get_db_archive_config(v_tag)
            v_json  = json.dumps(result)
            write_log("{0} dbops api interface /read_config_archive success!".format(get_time()))
            write_log("入口参数：\n\t{0}".format(v_tag))
            write_log("出口参数：")
            if result['code']==200:
                print_dict(result['msg'])
            self.write(v_json)
        except Exception as e:
            write_log(str(e))
            result['code'] = -1
            result['msg'] = str(e)
            self.write(v_json)

class read_config_monitor(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag  = self.get_argument("tag")
            result = get_db_monitor_config(v_tag)
            v_json = json.dumps(result)
            write_log("{0} dbops api interface /read_config_monitor success!".format(get_time()))
            if result['code'] == 200:
                print_dict(result['msg'])
            self.write(v_json)
        except Exception as e:
            write_log(str(e))
            result['code'] = -1
            result['msg'] = str(e)
            self.write(v_json)


class read_config_db(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            result = {}
            result['code'] = 200
            result['msg'] = db_config_info()
            v_json = json.dumps(result)
            self.write(v_json)
        except Exception as e:
            result['code'] = -1
            result['msg'] = str(e)
            self.write(v_json)


class read_datax_config_sync(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            result  = get_datax_sync_config(v_tag)
            v_json  = json.dumps(result)
            write_log("{0} dbops api interface /read_datax_config_sync success!".format(get_time()))
            write_log("入口参数：\n\t{0}".format(v_tag))
            write_log("出口参数：")
            if result['code']==200:
                print_dict(result['msg'])
            self.write(v_json)
        except Exception as e:
            write_log(str(e))
            result['code'] = -1
            result['msg'] = str(e)
            self.write(v_json)

class read_datax_templete(tornado.web.RequestHandler):
    def post(self):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        v_id    = self.get_argument("id")
        result  = get_datax_sync_templete(v_id)
        v_json  = json.dumps(result)
        print('read_datax_templete=', result)
        print('v_json=', v_json)
        if result['code'] == 200:
            write_log("{0} dbops api interface /read_datax_templete success!".format(get_time()))
            write_log("入口参数：\n\t{0}".format(v_id))
            write_log("出口参数：")
            print_dict(result['msg'])
            self.write(v_json)
        else:
            print_dict(result['msg'])

class set_crontab_local(tornado.web.RequestHandler):
    ##################################################################################
    #  test: curl -XPOST 10.2.39.76:8181/set_crontab -d 'tag=mysql_10_2_39_80_3306'  #
    #  question：crontab execute more ,task repeat ?                                 #
    ##################################################################################
    def post(self):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        v_tag          = self.get_argument("tag")
        v_msg          = get_db_config(v_tag)
        v_cron         = CronTab(user=True)
        v_cmd          = '$PYTHON3_HOME/bin/python3 {0}/{1} -tag {2}'.format(v_msg['script_path'],v_msg['script_file'],v_msg['db_tag'])
        job            = v_cron.new(command=v_cmd)
        job.setall(v_msg['run_time'])
        job.enable()
        v_cron.write()
        result         = {}
        result['code'] = 200
        result['msg']  = v_msg
        v_json = json.dumps(result)
        write_log("{0} dbops api interface /set_crontab success!".format(get_time()))
        write_log("入口参数：\n\t{0}".format(v_tag))
        write_log("出口参数：")
        write_log(result['msg'] )
        self.write(v_json)

class set_crontab_remote(tornado.web.RequestHandler):
    def post(self):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        v_tag    = self.get_argument("tag")
        result   = write_remote_crontab(v_tag)
        v_json   = json.dumps(result)
        write_log("{0} dbops api interface /push_script success!".format(get_time()))
        write_log("入口参数：\n\t{0}".format(v_tag))
        write_log("出口参数：")
        print_dict(result['msg'] )
        self.write(v_json)

class push_script_remote(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            print('v_tag=',v_tag)
            result  = transfer_remote_file(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                self.write(v_json)
            else:
                result  = run_remote_cmd(v_tag)
                result  = write_remote_crontab(v_tag)
                v_json  = json.dumps(result)
                print("{0} dbops api interface /push_script_remote success!".format(get_time()))
                print("入口参数：\n\t{0}".format(v_tag))
                print("出口参数：")
                print_dict(result['msg'] )
                self.write(v_json)
        except Exception as e:
            print('push_script_remote error!')
            print(str(e))

class run_script_remote(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            print('v_tag=',v_tag)
            result  = transfer_remote_file(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                self.write(v_json)
            else:
                result  = run_remote_cmd(v_tag)
                result  = run_remote_backup_task(v_tag)
                v_json  = json.dumps(result)
                print("{0} dbops api interface /run_script_remote success!".format(get_time()))
                print("入口参数：\n\t{0}".format(v_tag))
                print("出口参数：")
                print_dict(result['msg'] )
                self.write(v_json)
        except Exception as e:
            print('push_script_remote error!')
            print(str(e))

class stop_script_remote(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            print('v_tag=',v_tag)
            result  = stop_remote_backup_task(v_tag)
            v_json  = json.dumps(result)
            print("{0} dbops api interface /stop_script_remote success!".format(get_time()))
            print("入口参数：\n\t{0}".format(v_tag))
            print("出口参数：")
            print_dict(result['msg'] )
            self.write(v_json)
        except Exception as e:
            print('stop_script_remote error!')
            print(str(e))

class run_script_remote_sync(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            print('v_tag=',v_tag)
            result  = transfer_remote_file_sync(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                self.write(v_json)
            else:
                result  = run_remote_cmd_sync(v_tag)
                result  = run_remote_sync_task(v_tag)
                v_json  = json.dumps(result)
                print("{0} dbops api interface /run_script_remote_sync success!".format(get_time()))
                print("入口参数：\n\t{0}".format(v_tag))
                print("出口参数：")
                print_dict(result['msg'] )
                self.write(v_json)
        except Exception as e:
            print('push_script_remote error!')
            print(str(e))

class run_datax_remote_sync(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            print('v_tag=',v_tag)
            result  = transfer_datax_remote_file_sync(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                self.write(v_json)
            else:
                result  = run_remote_datax_task(v_tag)
                v_json  = json.dumps(result)
                print("{0} dbops api interface /run_script_remote_sync success!".format(get_time()))
                print_dict(result['msg'] )
                self.write(v_json)
        except Exception as e:
            print('push_script_remote error!')
            print(str(e))

class run_script_remote_transfer(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag = self.get_argument("tag")
            print('v_tag=', v_tag)
            result = transfer_remote_file_transfer(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                self.write(v_json)
            else:
                result = run_remote_cmd_transfer(v_tag)
                result = run_remote_transfer_task(v_tag)
                v_json = json.dumps(result)
                print("{0} dbops api interface /run_script_remote_sync success!".format(get_time()))
                print_dict(result['msg'])
                self.write(v_json)
        except Exception as e:
            print('push_script_remote error!')
            print(str(e))

class run_script_remote_archive(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag = self.get_argument("tag")
            print('v_tag=', v_tag)
            result = transfer_remote_file_archive(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                self.write(v_json)
            else:
                result = run_remote_cmd_archive(v_tag)
                result = run_remote_archive_task(v_tag)
                v_json = json.dumps(result)
                print("{0} dbops api interface /run_script_remote_archive success!".format(get_time()))
                print_dict(result['msg'])
                self.write(v_json)
        except Exception as e:
            print('push_script_remote error!')
            print(str(e))


class stop_script_remote_sync(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            print('v_tag=',v_tag)
            result  = stop_remote_sync_task(v_tag)
            v_json  = json.dumps(result)
            print("{0} dbops api interface /stop_script_remote_sync success!".format(get_time()))
            self.write(v_json)
        except Exception as e:
            traceback.print_stack()
            print('stop_script_remote_sync error!'+str(e))

class stop_script_remote_transfer(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            result  = stop_remote_transfer_task(v_tag)
            v_json  = json.dumps(result)
            print("{0} dbops api interface /stop_remote_transfer_task success!".format(get_time()))
            self.write(v_json)
        except Exception as e:
            print('stop_remote_transfer_task error!'+ traceback.format_exc())

class stop_script_remote_archive(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            result  = stop_remote_archive_task(v_tag)
            v_json  = json.dumps(result)
            print("{0} dbops api interface /stop_remote_transfer_task success!".format(get_time()))
            self.write(v_json)
        except Exception as e:
            print('stop_remote_transfer_task error!'+ traceback.format_exc())


class stop_datax_remote_sync(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            result  = stop_datax_sync_task(v_tag)
            v_json  = json.dumps(result)
            print("{0} dbops api interface /stop_datax_remote_sync success!".format(get_time()))
            self.write(v_json)
        except Exception as e:
            print('stop_remote_transfer_task error!'+ traceback.format_exc())

class push_script_remote_sync(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            result  = transfer_remote_file_sync(v_tag)
            if result['code']!=200:
               v_json = json.dumps(result)
               print('v_json=',v_json)
               self.write(v_json)
               return

            result  = run_remote_cmd_sync(v_tag)
            if result['code']!=200:
               v_json = json.dumps(result)
               print(v_json)
               self.write(v_json)
               return

            result  = write_remote_crontab_sync(v_tag)
            if result['code']!=200:
               v_json = json.dumps(result)
               print(v_json)
               self.write(v_json)
               return

            v_json  = json.dumps(result)
            write_log("{0} dbops api interface /push_script_remote_sync success!".format(get_time()))
            write_log("入口参数：\n\t{0}".format(v_tag))
            write_log("出口参数：")
            print_dict(result['msg'] )
            print(v_json)
            self.write(v_json)
        except Exception as e:
            print(str(e))
            write_log(str(e))

class push_script_remote_transfer(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag = self.get_argument("tag")
            result = transfer_remote_file_transfer(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                print('v_json=', v_json)
                self.write(v_json)
                return

            result = run_remote_cmd_transfer(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                print(v_json)
                self.write(v_json)
                return

            v_json = json.dumps(result)
            write_log("{0} dbops api interface /push_script_remote_transfer success!".format(get_time()))
            write_log("入口参数：\n\t{0}".format(v_tag))
            write_log("出口参数：")
            print_dict(result['msg'])
            print(v_json)
            self.write(v_json)
        except Exception as e:
            print(str(e))
            write_log(str(e))

class push_script_remote_archive(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag = self.get_argument("tag")
            result = transfer_remote_file_archive(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                print('v_json=', v_json)
                self.write(v_json)
                return

            result = run_remote_cmd_archive(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                print(v_json)
                self.write(v_json)
                return

            v_json = json.dumps(result)
            write_log("{0} dbops api interface /push_script_remote_transfer success!".format(get_time()))
            write_log("入口参数：\n\t{0}".format(v_tag))
            write_log("出口参数：")
            print_dict(result['msg'])
            print(v_json)
            self.write(v_json)
        except Exception as e:
            print(str(e))
            write_log(str(e))

class push_script_remote_monitor(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag = self.get_argument("tag")
            result = transfer_remote_file_monitor(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                print('v_json=', v_json)
                self.write(v_json)
                return

            result = run_remote_cmd_monitor(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                print(v_json)
                self.write(v_json)
                return

            result = write_remote_crontab_monitor(v_tag)
            if result['code'] != 200:
                v_json = json.dumps(result)
                print(v_json)
                self.write(v_json)
                return

            v_json = json.dumps(result)
            write_log("{0} dbops api interface /push_script_remote_monitor success!".format(get_time()))
            write_log("入口参数：\n\t{0}".format(v_tag))
            write_log("出口参数：")
            print_dict(result['msg'])
            print(v_json)
            self.write(v_json)
        except Exception as e:
            traceback.format_exc()


class push_datax_remote_sync(tornado.web.RequestHandler):
    def post(self):
        try:
            self.set_header("Content-Type", "application/json; charset=UTF-8")
            v_tag   = self.get_argument("tag")
            result  = transfer_datax_remote_file_sync(v_tag)
            if result['code']!=200:
               v_json = json.dumps(result)
               print('v_json=',v_json)
               self.write(v_json)
               return

            result  = run_datax_remote_cmd_sync(v_tag)
            if result['code']!=200:
               v_json = json.dumps(result)
               print(v_json)
               self.write(v_json)
               return

            result  = write_datax_remote_crontab_sync(v_tag)
            if result['code']!=200:
               v_json = json.dumps(result)
               print(v_json)
               self.write(v_json)
               return

            v_json  = json.dumps(result)
            write_log("{0} dbops api interface /push_datax_remote_sync success!".format(get_time()))
            write_log("入口参数：\n\t{0}".format(v_tag))
            write_log("出口参数：")
            print_dict(result['msg'] )
            print(v_json)
            self.write(v_json)
        except Exception as e:
            print(str(e))

class write_sync_log(tornado.web.RequestHandler):
    def post(self):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        v_tag = self.get_argument("tag")
        config = json.loads(v_tag)
        result = save_sync_log(config)
        v_json = json.dumps(result)
        write_log("{0} dbops api interface /write_sync_log success!".format(get_time()))
        write_log("入口参数:")
        print_dict(config)
        write_log("出口参数：")
        print_dict(result)
        self.write(v_json)

class write_datax_sync_log(tornado.web.RequestHandler):
    def post(self):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        v_tag = self.get_argument("tag")
        config = json.loads(v_tag)
        result = save_datax_sync_log(config)
        v_json = json.dumps(result)
        print("{0} dbops api interface /write_datax_sync_log success!".format(get_time()))
        print_dict(config)
        print('write_datax_sync_log=',v_json)
        self.write(v_json)

class write_transfer_log(tornado.web.RequestHandler):
    def post(self):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        v_tag = self.get_argument("tag")
        config = json.loads(v_tag)
        result = save_transfer_log(config)
        v_json = json.dumps(result)
        print("{0} dbops api interface /write_sync_log success!".format(get_time()))
        self.write(v_json)

class write_archive_log(tornado.web.RequestHandler):
    def post(self):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        v_tag = self.get_argument("tag")
        config = json.loads(v_tag)
        result = save_archive_log(config)
        v_json = json.dumps(result)
        print("{0} dbops api interface /write_archive_log success!".format(get_time()))
        self.write(v_json)

class write_monitor_log(tornado.web.RequestHandler):
    def post(self):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        v_tag = self.get_argument("tag")
        config = json.loads(v_tag)
        result = save_monitor_log(config)
        v_json = json.dumps(result)
        print("{0} dbops api interface /write_archive_log success!".format(get_time()))
        self.write(v_json)


class write_sync_log_detail(tornado.web.RequestHandler):
    def post(self):
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        v_tag = self.get_argument("tag")
        config = json.loads(v_tag)
        result = save_sync_log_detail(config)
        v_json = json.dumps(result)
        write_log("{0} dbops api interface /write_sync_log_detail success!".format(get_time()))
        write_log("入口参数:")
        print_dict(config)
        write_log("出口参数：")
        print_dict(result)
        self.write(v_json)

define("port", default=sys.argv[1], help="run on the given port", type=int)

class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            #备份API接口
            (r"/read_config_backup" , read_config_backup),
            (r"/read_db_decrypt"    , read_db_decrypt),
            (r"/update_backup_status",write_backup_status),
            (r"/write_backup_total" , write_backup_total),
            (r"/write_backup_detail", write_backup_detail),
            (r"/set_crontab_local"  , set_crontab_local),
            (r"/set_crontab_remote" , set_crontab_remote),
            (r"/push_script_remote" , push_script_remote),
            (r"/run_script_remote"  , run_script_remote),
            (r"/stop_script_remote" , stop_script_remote),

            #同步API接口
            (r"/read_config_sync"       , read_config_sync),
            (r"/push_script_remote_sync", push_script_remote_sync),
            (r"/write_sync_log"         , write_sync_log),
            (r"/write_sync_log_detail"  , write_sync_log_detail),
            (r"/run_script_remote_sync",  run_script_remote_sync),
            (r"/stop_script_remote_sync", stop_script_remote_sync),

            #DataX同步API接口
            (r"/push_datax_remote_sync", push_datax_remote_sync),
            (r"/read_datax_config_sync", read_datax_config_sync),
            (r"/read_datax_templete",    read_datax_templete),
            (r"/run_datax_remote_sync",  run_datax_remote_sync),
            (r"/stop_datax_remote_sync", stop_datax_remote_sync),
            (r"/write_datax_sync_log",   write_datax_sync_log),

            #传输API接口
            (r"/read_config_transfer", read_config_transfer),
            (r"/push_script_remote_transfer", push_script_remote_transfer),
            (r"/write_transfer_log", write_transfer_log),
            (r"/run_script_remote_transfer", run_script_remote_transfer),
            (r"/stop_script_remote_transfer", stop_script_remote_transfer),

            # 归档API接口
            (r"/read_config_archive", read_config_archive),
            (r"/push_script_remote_archive", push_script_remote_archive),
            (r"/write_archive_log", write_archive_log),
            (r"/run_script_remote_archive", run_script_remote_archive),
            (r"/stop_script_remote_archive", stop_script_remote_archive),

            # 监控API接口
            (r"/read_config_monitor", read_config_monitor),
            (r"/read_config_db", read_config_db),
            (r"/push_script_remote_monitor", push_script_remote_monitor),
            (r"/write_monitor_log", write_monitor_log),
        ]
        tornado.web.Application.__init__(self, handlers)

if __name__ == '__main__':
    tornado.options.parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(sys.argv[1])
    print('Dbapi Api Server running {0} port ...'.format(sys.argv[1]))
    tornado.ioloop.IOLoop.instance().start()



