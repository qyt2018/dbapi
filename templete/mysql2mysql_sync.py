#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time : 2019/1/30 9:31
# @Author : 马飞
# @File : sync_mysql2mongo.py
# @Func : MySQL->MySQL增量同步（实时车流）
# @Software: PyCharm

import sys,time
import traceback
import configparser
import warnings
import pymssql
import pymysql
import datetime
import hashlib
import smtplib
from email.mime.text import MIMEText
import json
import urllib.parse
import urllib.request
import ssl

def set_sync_flag(config,flag):
    cr = config['db_mysql_desc3'].cursor()
    sql="""select count(0) from sync.t_mysql2mysql_sync_log 
            where market_id={0} and type='{1}'""".format(config['sync_col_val'],config['sync_type'])
    cr.execute(sql)
    rs=cr.fetchone()
    if rs[0]>0:
        cr.execute("""update sync.t_mysql2mysql_sync_log 
                           set status='{0}',last_update_date=now() 
                         where market_id={1} and type='{2}'
                   """.format(flag,config['sync_col_val'], config['sync_type']))

    else:
        cr.execute("""insert into sync.t_mysql2mysql_sync_log(market_id,type,status,create_date,last_update_date) 
                        values({0},'{1}','{2}',now(),now())""".format(config['sync_col_val'],config['sync_type'],flag))
    config['db_mysql_desc3'].commit()
    cr.close()

def send_mail465(p_from_user,p_from_pass,p_to_user,p_title,p_content):
    to_user=p_to_user.split(",")
    try:
        msg = MIMEText(p_content,'html','utf-8')
        msg["Subject"] = p_title
        msg["From"]    = p_from_user
        msg["To"]      = ",".join(to_user)
        server = smtplib.SMTP_SSL("smtp.exmail.qq.com", 465)
        server.set_debuglevel(0)
        server.login(p_from_user, p_from_pass)
        server.sendmail(p_from_user, to_user, msg.as_string())
        server.quit()
    except smtplib.SMTPException as e:
        print(e)

def send_mail(p_from_user,p_from_pass,p_to_user,p_title,p_content):
    to_user=p_to_user.split(",")
    try:
        msg = MIMEText(p_content,'html','utf-8')
        msg["Subject"] = p_title
        msg["From"]    = p_from_user
        msg["To"]      = ",".join(to_user)
        server = smtplib.SMTP("smtp.exmail.qq.com", 25)
        server.set_debuglevel(0)
        server.login(p_from_user, p_from_pass)
        server.sendmail(p_from_user, to_user, msg.as_string())
        server.quit()
    except smtplib.SMTPException as e:
        print(e)

def send_mail25(p_from_user,p_from_pass,p_to_user,p_title,p_content):
    to_user=p_to_user.split(",")
    try:
        msg = MIMEText(p_content,'html','utf-8')
        msg["Subject"] = p_title
        msg["From"]    = p_from_user
        msg["To"]      = ",".join(to_user)
        server = smtplib.SMTP("smtp.exmail.qq.com", 25)
        server.set_debuglevel(0)
        server.login(p_from_user, p_from_pass)
        server.sendmail(p_from_user, to_user, msg.as_string())
        server.quit()
    except smtplib.SMTPException as e:
        print(e)

def exception_info():
    e_str=traceback.format_exc()
    return e_str[e_str.find("pymysql.err."):]

def get_now():
    return datetime.datetime.now().strftime("%H:%M:%S")

def get_time():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_date():
    return datetime.datetime.now().strftime("%Y%m%d")

def get_ds_mysql(ip,port,service ,user,password):
    conn = pymysql.connect(host=ip, port=int(port), user=user, passwd=password, db=service, charset='utf8')
    return conn

def get_ds_sqlserver(ip,port,service,user,password):
    conn = pymssql.connect(host=ip, port=int(port), user=user, password=password, database=service,charset='utf8')
    return conn

def get_db_mysql_sour(config):
    return get_ds_mysql(config['db_mysql_sour_ip'],config['db_mysql_sour_port'],config['db_mysql_sour_service'],\
                        config['db_mysql_sour_user'],config['db_mysql_sour_pass'])

def get_db_mysql_desc(config):
    return get_ds_mysql(config['db_mysql_desc_ip'],config['db_mysql_desc_port'],config['db_mysql_desc_service'],\
                        config['db_mysql_desc_user'],config['db_mysql_desc_pass'])

def get_html_contents(config):
    tjrq    = get_time()
    db_sour = config['db_mysql_sour']
    db_desc = config['db_mysql_desc']
    tbody1  = '''<tr><td width=10%><b>源始库</b></td><td width=50%>{0}</td></tr>
                 <tr><td width=10%><b>目标库</b></td><td width=50%>{1}</td></tr>
                 <tr><td width=10%><b>批大小</b></td><td width=50%>{2}&nbsp;rows</td></tr>               
                 <tr><td width=10%><b>增量同步间隔</b></td><td width=50%>{3}s</td></tr>
                 <tr><td width=10%><b>邮件发送间隔</b></td><td width=50%>{4}s</td></tr> 
             '''.format(config['db_mysql_sour_string'],config['db_mysql_desc_string'],
                        config['batch_size'],config['sync_gap'],config['mail_gap'])

    thead2 = '''<tr><td width=10%>表名</td>
                    <td width=10%>主键</td>
                    <td width=10%>时间列</td>
                    <td width=10%>同步策略</td>
                    <td width=10%>行数(MySQL【项目】)</td>
                    <td width=10%>行数(MySQL【生产】)</td>
                </tr>
             '''
    v_temp = '''<tr>
                    <td>{0}</td><td>{1}</td><td>{2}</td><td>{3}</td><td>{4}</td><td>{5}</td>
                </tr>
             '''
    tbody2 = ''
    for i in config['sync_table'].split(","):
        method = ''
        tab    = i.split(':')[0]
        col    = i.split(':')[1]
        day    = i.split(':')[2]
        v_pks  = get_sync_table_pk_names(db_sour, tab)

        if day == '' or v_pks=='':
            method = '全量'
        else:
            method = '增量,最近 {0} {1}'.format(day, config['sync_time_type_name'])

        v_where      = get_sync_where_incr_mysql_rq(i, config,tjrq)
        v_pks        = get_sync_table_pk_names(db_sour, tab)
        s_rows_total = str(get_sync_table_total_rows(db_sour,tab,''))
        m_rows_total = str(get_sync_table_total_rows(db_desc, tab, ''))
        s_rows_incr  = str(get_sync_table_total_rows(db_sour, tab, v_where))
        m_rows_incr  = str(get_sync_table_total_rows(db_desc, tab, v_where))
        s_rows       = '总数:{0},增量:{1}'.format(s_rows_total,s_rows_incr)
        m_rows       = '总数:{0},增量:{1}'.format(m_rows_total,m_rows_incr)
        tbody2       = tbody2+v_temp.format(tab,v_pks,col,method,s_rows,m_rows)

    tbody3 ='''<tr><td width=100%>{0}</td></tr>'''.format(get_sync_log(config))
    v_html ='''<html>
                <head>
                   <style type="text/css">
                       .xwtable {width: 100%;border-collapse: collapse;border: 1px solid #ccc;}
                       .xwtable thead td {font-size: 12px;color: #333333;
                                          text-align: center;background: url(table_top.jpg) repeat-x top center;
                                          border: 1px solid #ccc; font-weight:bold;}
                       .xwtable thead th {font-size: 12px;color: #333333;
                                          text-align: center;background: url(table_top.jpg) repeat-x top center;
                                          border: 1px solid #ccc; font-weight:bold;}
                       .xwtable tbody tr {background: #fff;font-size: 12px;color: #666666;}
                       .xwtable tbody tr.alt-row {background: #f2f7fc;}
                       .xwtable td{line-height:20px;text-align: left;padding:4px 10px 3px 10px;height: 18px;border: 1px solid #ccc;}
                       span { color:red;}
                   </style>
                </head>
                <body>
                  <h4>同步配置：</h4>
                  <table class="xwtable">
                     <tbody>\n'''+tbody1+'\n</tbody>\n'+'''
                  </table>
                  
                  <h4>同步表列表：</h4>
                  <table class="xwtable">
                     <thead>\n'''+thead2+'\n</thead>\n'+'''
                     <tbody>\n'''+tbody2+'\n</tbody>\n'+'''
                  </table>
                  
                  <h4>最近十分钟同步日志：</h4>
                  <table class="xwtable">
                     <tbody>\n'''+tbody3+'\n</tbody>\n'+'''
                  </table>
                  
                </body>
              </html>
           '''
    return v_html

def get_sync_time_type_name(sync_time_type):
    if sync_time_type=="day":
       return '天'
    elif sync_time_type=="hour":
       return '小时'
    elif sync_time_type=="min":
       return '分'
    else:
       return ''

def aes_decrypt(p_password,p_key):
    values = {
        'password': p_password,
        'key':p_key
    }
    url = 'http://$$API_SERVER$$/read_db_decrypt'
    context = ssl._create_unverified_context()
    data = urllib.parse.urlencode(values).encode(encoding='UTF-8')
    req = urllib.request.Request(url, data=data)
    res = urllib.request.urlopen(req, context=context)
    res = json.loads(res.read())
    if res['code'] == 200:
        print('接口read_db_decrypt 调用成功!')
        config = res['msg']
        return config
    else:
        print('接口read_db_decrypt 调用失败!,{0}'.format(res['msg']))
        sys.exit(0)

def get_config_from_db(tag,workdir):
    try:
        values = {
            'tag': tag
        }
        print('values=', values)
        url = 'http://$$API_SERVER$$/read_config_sync'
        context = ssl._create_unverified_context()
        data = urllib.parse.urlencode(values).encode(encoding='UTF-8')
        print('data=', data)
        req = urllib.request.Request(url, data=data)
        res = urllib.request.urlopen(req, context=context)
        res = json.loads(res.read())
        print(res, res['code'])
        if res['code'] == 200:
            print('接口调用成功!')
            try:
                print(res['msg'])
                config = res['msg']
                config['sync_time_type_name']   = get_sync_time_type_name(config['sync_time_type'])
                db_sour_ip                      = config['sync_db_sour'].split(':')[0]
                db_sour_port                    = config['sync_db_sour'].split(':')[1]
                db_sour_service                 = config['sync_db_sour'].split(':')[2]
                db_sour_user                    = config['sync_db_sour'].split(':')[3]
                db_sour_pass                    = aes_decrypt(config['sync_db_sour'].split(':')[4],db_sour_user)
                db_dest_ip                      = config['sync_db_dest'].split(':')[0]
                db_dest_port                    = config['sync_db_dest'].split(':')[1]
                db_dest_service                 = config['sync_db_dest'].split(':')[2]
                db_dest_user                    = config['sync_db_dest'].split(':')[3]
                db_dest_pass                    = aes_decrypt(config['sync_db_dest'].split(':')[4],db_dest_user)
                config['db_mysql_sour_ip']      = db_sour_ip
                config['db_mysql_sour_port']    = db_sour_port
                config['db_mysql_sour_service'] = db_sour_service
                config['db_mysql_sour_user']    = db_sour_user
                config['db_mysql_sour_pass']    = db_sour_pass
                config['db_mysql_desc_ip']      = db_dest_ip
                config['db_mysql_desc_port']    = db_dest_port
                config['db_mysql_desc_service'] = db_dest_service
                config['db_mysql_desc_user']    = db_dest_user
                config['db_mysql_desc_pass']    = db_dest_pass
                config['db_mysql_sour_string']  = db_sour_ip + ':' + db_sour_port + '/' + db_sour_service
                config['db_mysql_desc_string']  = db_dest_ip + ':' + db_dest_port + '/' + db_dest_service
                config['db_mysql_sour']         = get_ds_mysql(db_sour_ip, db_sour_port, db_sour_service, db_sour_user, db_sour_pass)
                config['db_mysql_sour2']        = get_ds_mysql(db_sour_ip, db_sour_port, db_sour_service, db_sour_user, db_sour_pass)
                config['db_mysql_sour3']        = get_ds_mysql(db_sour_ip, db_sour_port, db_sour_service, db_sour_user, db_sour_pass)
                config['db_mysql_desc']         = get_ds_mysql(db_dest_ip, db_dest_port, db_dest_service, db_dest_user, db_dest_pass)
                config['db_mysql_desc3']        = get_ds_mysql(db_dest_ip, db_dest_port, db_dest_service, db_dest_user, db_dest_pass)
                config['run_mode']              = 'remote'
                #write local config file
                write_local_config_file(config)
                return config
            except Exception as e:
                v_error = '从接口配置获取数据库连接对象时出现异常:{0}'.format(traceback.format_exc())
                print(v_error)
                exception_connect_db(config, v_error)
                exit(0)
        else:
            print('接口调用失败!,{0}'.format(res['msg']))  # 发异常邮件
            v_title = '数据同步接口异常[★]'
            v_content = '''<table class='xwtable'>
                                           <tr><td  width="30%">接口地址</td><td  width="70%">$$interface$$</td></tr>
                                           <tr><td  width="30%">接口参数</td><td  width="70%">$$parameter$$</td></tr>
                                           <tr><td  width="30%">错误信息</td><td  width="70%">$$error$$</td></tr>            
                                       </table>'''
            v_content = v_content.replace('$$interface$$', url)
            v_content = v_content.replace('$$parameter$$', json.dumps(values))
            v_content = v_content.replace('$$error$$', res['msg'])
            exception_interface(v_title, v_content)
            sys.exit(0)
    except Exception as e :
        file_name = workdir + '/config/' + tag + '.ini'
        print('接口调用失败:{0}'.format(str(e)))
        print('从本地读取最近一次配置文件：{0}'.format(file_name))
        v_title   = '数据同步接口异常[★★]'
        v_desc    = '同步任务运行于本地配置文件模式中，请尽快处理! 自动从本地读取最近一次配置文件进行同步：{0}'.format(file_name)
        v_content = '''<table class='xwtable'>
                           <tr><td  width="30%">接口地址</td><td  width="70%">$$interface$$</td></tr>
                           <tr><td  width="30%">接口参数</td><td  width="70%">$$parameter$$</td></tr>
                           <tr><td  width="30%">错误信息</td><td  width="70%">$$error$$</td></tr> 
                           <tr><td  width="30%">说明信息</td><td  width="70%">$$desc$$</td></tr>               
                       </table>'''
        v_content = v_content.replace('$$interface$$', url)
        v_content = v_content.replace('$$parameter$$',  json.dumps(values))
        v_content = v_content.replace('$$error$$', traceback.format_exc())
        v_content = v_content.replace('$$desc$$', v_desc)
        exception_interface(v_title, v_content)
        config = get_config(file_name, tag)
        return config

def write_log(msg):
    file_name   = '/tmp/mysql_sync.log'
    file_handle = open(file_name, 'a+')
    file_handle.write(msg + '\n')
    file_handle.close()

def write_sync_log(config):
    v_tag = {
        'sync_tag'        : config['sync_tag'],
        'create_date'     : get_time(),
        'duration'        : config['sync_duration'],
        'amount'          : config['sync_amount']
    }
    v_msg = json.dumps(v_tag)
    values = {
        'tag': v_msg
    }
    #write_log('values=' + json.dump(values))
    url = 'http://$$API_SERVER$$/write_sync_log'
    context = ssl._create_unverified_context()
    data = urllib.parse.urlencode(values).encode(encoding='UTF-8')
    req = urllib.request.Request(url, data=data)
    res = urllib.request.urlopen(req, context=context)
    res = json.loads(res.read())
    print(res, res['code'])
    if res['code'] == 200:
        write_log('Interface write_sync_log call successful!')
    else:
        write_log('Interface write_sync_log call failed!')

def write_sync_log_detail(config):
    v_tag = {
        'sync_tag'        : config['sync_tag'],
        'create_date'     : get_time(),
        'sync_table'      : config['sync_table_inteface'],
        'sync_amount'     : config['sync_amount'],
        'duration'        : config['sync_duration']
    }
    v_msg = json.dumps(v_tag)
    values = {
        'tag': v_msg
    }
    print('write_sync_log_detail=', values)
    #write_log('values='+json.dump(values))
    url     = 'http://$$API_SERVER$$/write_sync_log_detail'
    context = ssl._create_unverified_context()
    data    = urllib.parse.urlencode(values).encode(encoding='UTF-8')
    req     = urllib.request.Request(url, data=data)
    res     = urllib.request.urlopen(req, context=context)
    res     = json.loads(res.read())
    print(res, res['code'])
    if res['code'] == 200:
        write_log('Interface write_sync_log_detail call successful!')
    else:
        write_log('Interface write_sync_log_detail call failed!')

def get_config(fname,tag):
    try:
        config = {}
        cfg=configparser.ConfigParser()
        cfg.read(fname,encoding="utf-8-sig")
        sync_server_sour                  = cfg.get("sync","sync_db_mysql_sour")
        sync_server_dest                  = cfg.get("sync","sync_db_mysql_desc")
        config['sync_table']              = cfg.get("sync", "sync_table").lower()
        config['batch_size']              = cfg.get("sync", "batch_size")
        config['batch_size_incr']         = cfg.get("sync", "batch_size_incr")
        config['sync_gap']                = cfg.get("sync", "sync_gap")
        config['sync_col_name']           = cfg.get("sync", "sync_col_name")
        config['sync_col_val']            = cfg.get("sync", "sync_col_val")
        config['sync_time_type']          = cfg.get("sync","sync_time_type")
        config['sync_time_type_name']     = get_sync_time_type_name(config['sync_time_type'])
        db_sour_ip                        = sync_server_sour.split(':')[0]
        db_sour_port                      = sync_server_sour.split(':')[1]
        db_sour_service                   = sync_server_sour.split(':')[2]
        db_sour_user                      = sync_server_sour.split(':')[3]
        db_sour_pass                      = sync_server_sour.split(':')[4]
        db_dest_ip                        = sync_server_dest.split(':')[0]
        db_dest_port                      = sync_server_dest.split(':')[1]
        db_dest_service                   = sync_server_dest.split(':')[2]
        db_dest_user                      = sync_server_dest.split(':')[3]
        db_dest_pass                      = sync_server_dest.split(':')[4]
        config['db_mysql_sour_ip']        = db_sour_ip
        config['db_mysql_sour_port']      = db_sour_port
        config['db_mysql_sour_service']   = db_sour_service
        config['db_mysql_sour_user']      = db_sour_user
        config['db_mysql_sour_pass']      = db_sour_pass
        config['db_mysql_desc_ip']        = db_dest_ip
        config['db_mysql_desc_port']      = db_dest_port
        config['db_mysql_desc_service']   = db_dest_service
        config['db_mysql_desc_user']      = db_dest_user
        config['db_mysql_desc_pass']      = db_dest_pass
        config['db_mysql_sour_string']    = db_sour_ip+':'+db_sour_port+'/'+db_sour_service
        config['db_mysql_desc_string']    = db_dest_ip+':'+db_dest_port+'/'+db_dest_service
        config['db_mysql_sour']           = get_ds_mysql(db_sour_ip, db_sour_port ,db_sour_service, db_sour_user, db_sour_pass)
        config['db_mysql_sour2']          = get_ds_mysql(db_sour_ip, db_sour_port, db_sour_service, db_sour_user, db_sour_pass)
        config['db_mysql_sour3']          = get_ds_mysql(db_sour_ip, db_sour_port, db_sour_service, db_sour_user, db_sour_pass)
        config['db_mysql_desc']           = get_ds_mysql(db_dest_ip, db_dest_port ,db_dest_service, db_dest_user, db_dest_pass)
        config['db_mysql_desc3']          = get_ds_mysql(db_dest_ip, db_dest_port, db_dest_service, db_dest_user, db_dest_pass)
        config['run_mode']                = 'local'
        config['sync_tag']                = tag
        return config
    except Exception as e:
        v_error = '从本地读取最近一次本地配置文件获取数据源时出现异常:{0}'.format(traceback.format_exc())
        print(v_error)
        exception_connect_db(config, v_error)
        exit(0)

def check_mysql_tab_exists(config,tab):
   db=config['db_mysql_desc']
   cr=db.cursor()
   sql="""select count(0) from information_schema.tables
            where table_schema=database() and table_name='{0}'""".format(tab )
   config['run_sql'] = sql
   cr.execute(sql)
   rs=cr.fetchone()
   cr.close()
   db.commit()
   return rs[0]

def get_mysql_tab_rows(config,tab):
   db=config['db_mysql_desc3']
   cr=db.cursor()
   sql="""select count(0) from {0}""".format(tab)
   config['run_sql'] = sql
   cr.execute(sql)
   rs=cr.fetchone()
   cr.close()
   db.commit()
   return rs[0]

def get_mysql_tab_incr_rows(config,tab):
   db=config['db_mysql_desc3']
   cr=db.cursor()
   sql="""select count(0) from {0}""".format(tab )
   config['run_sql'] = sql
   cr.execute(sql)
   rs=cr.fetchone()
   cr.close()
   db.commit()
   return rs[0]

def check_mysql_tab_sync(config,tab):
   db=config['db_mysql_desc']
   cr=db.cursor()
   sql="select count(0) from {0}".format(tab)
   config['run_sql'] = sql
   cr.execute(sql)
   rs=cr.fetchone()
   cr.close()
   db.commit()
   return rs[0]

def check_mysql_tab_exists_pk(config,tab):
   db=config['db_mysql_sour']
   cr=db.cursor()
   sql = """select count(0) from information_schema.columns
              where table_schema=database() and table_name='{0}' and column_key='PRI'""".format(tab)
   config['run_sql'] = sql
   cr.execute(sql)
   rs=cr.fetchone()
   cr.close()
   db.commit()
   return rs[0]

def get_seconds(b):
    a=datetime.datetime.now()
    return int((a-b).total_seconds())

def print_dict(config):
    print('-'.ljust(85,'-'))
    print(' '.ljust(3,' ')+"name".ljust(20,' ')+'value')
    print('-'.ljust(85,'-'))
    for key in config:
      print(' '.ljust(3,' ')+key.ljust(20,' ')+'=',config[key])
    print('-'.ljust(85,'-'))

def format_sql(v_sql):
    return v_sql.replace("\\","\\\\").replace("'","\\'")

def get_tab_header_pkid(config,tab):
    db=config['db_mysql_sour']
    cr=db.cursor()
    cols=get_sync_table_cols_pkid(db,tab)
    sql="select {0} from {1} limit 1".format(cols,tab)
    config['run_sql'] = sql
    cr.execute(sql)
    desc=cr.description
    s1="insert into "+tab.lower()+"("
    s2=" values "
    s1=s1+cols+")"
    cr.close()
    return s1+s2

def get_tab_header(config,tab):
    db=config['db_mysql_sour']
    cr=db.cursor()
    sql="select * from {0} limit 1".format(tab)
    config['run_sql'] = sql
    cr.execute(sql)
    desc=cr.description
    s1="insert into "+tab.lower()+"("
    s2=" values "
    s1=s1+get_sync_table_cols(db,tab)+")"
    cr.close()
    return s1+s2

def f_get_table_ddl(config,tab):
    db_source = config['db_mysql_sour']
    cr_source = db_source.cursor()
    v_sql     ="""show create table {0}""".format(tab)
    config['run_sql'] = v_sql
    cr_source.execute(v_sql)
    rs=cr_source.fetchone()
    return rs[1]

def sync_mysql_ddl(config,debug):
    try:
        db_source = config['db_mysql_sour']
        cr_source = db_source.cursor()
        db_desc   = config['db_mysql_desc']
        cr_desc   = db_desc.cursor()
        for i in config['sync_table'].split(","):
            tab=i.split(':')[0]
            sql = """SELECT table_schema,table_name 
                                  FROM information_schema.tables
                                 WHERE table_schema=database() and table_name='{0}' order by table_name
                              """.format(tab)
            config['run_sql'] = sql
            cr_source.execute(sql)
            rs_source = cr_source.fetchall()
            for j in range(len(rs_source)):
                tab_name = rs_source[j][1].lower()
                if check_mysql_tab_exists_pk(config,tab)==0:
                   print("DB:{0},Table:{1} not exist primary,ignore!".format(config['db_mysql_sour_string'],tab_name))
                   v_cre_sql = f_get_table_ddl(config, tab_name)
                   if check_mysql_tab_exists(config, tab_name) > 0:
                       print("DB:{0},Table :{1} already exists!".format(config['db_mysql_sour_string'],tab_name))
                   else:
                       config['run_sql'] = v_cre_sql
                       cr_desc.execute(v_cre_sql)
                       print("Table:{0} creating success!".format(tab_name))
                       v_pk_sql="""ALTER TABLE {0} ADD COLUMN pkid INT(11) NOT NULL AUTO_INCREMENT FIRST, ADD PRIMARY KEY (pkid)
                                """.format(tab_name)
                       print( "Table:{0} add primary key pkid success!".format(tab_name))
                       config['run_sql'] = v_pk_sql
                       cr_desc.execute(v_pk_sql)
                       db_desc.commit()
                else:
                   #编写函数完成生成创表语句
                   v_cre_sql = f_get_table_ddl(config,tab_name)
                   if check_mysql_tab_exists(config,tab_name)>0:
                       print("DB:{0},Table :{1} already exists!".format(config['db_mysql_desc_string'],tab_name))
                   else:
                      config['run_sql'] = v_cre_sql
                      cr_desc.execute(v_cre_sql)
                      print("Table:{0} creating success!".format(tab_name))
                      db_desc.commit()
        cr_source.close()
        cr_desc.close()
    except Exception as e:
        print('sync_mysql_ddl exceptiion:'+traceback.format_exc())
        exception_running(config,traceback.format_exc())
        exit(0)

def get_sync_table_total_rows(db,tab,v_where):
    cr_source = db.cursor()
    v_sql="select count(0) from {0} {1}".format(tab,v_where)
    cr_source.execute(v_sql)
    rs_source=cr_source.fetchone()
    cr_source.close()
    return  rs_source[0]

def get_sync_table_pk_names(db,tab):
    cr_source = db.cursor()
    v_col=''
    v_sql="""select column_name 
              from information_schema.columns
              where table_schema=database() 
                and table_name='{0}' and column_key='PRI' order by ordinal_position
          """.format(tab)
    cr_source.execute(v_sql)
    rs_source = cr_source.fetchall()
    for i in list(rs_source):
        v_col=v_col+i[0]+','
    cr_source.close()
    return v_col[0:-1]

def get_sync_table_cols(db,tab):
    cr_source = db.cursor()
    v_col=''
    v_sql="""select concat('`',column_name,'`') from information_schema.columns
              where table_schema=database() and table_name='{0}'  order by ordinal_position
          """.format(tab)
    cr_source.execute(v_sql)
    rs_source = cr_source.fetchall()
    for i in list(rs_source):
        v_col=v_col+i[0]+','
    cr_source.close()
    return v_col[0:-1]

#获取非主键列以外的列名列表
def get_sync_table_cols_pkid(db,tab):
    return ','.join(get_sync_table_cols(db, tab).split(',')[1:])

def get_sync_table_pk_vals(db,tab):
    cr_source  = db.cursor()
    v_col=''
    v_sql="""SELECT column_name FROM information_schema.`COLUMNS`
             WHERE table_schema=DATABASE()
               AND table_name='{0}' AND column_key='PRI'  ORDER BY ordinal_position
          """.format(tab)
    cr_source.execute(v_sql)
    rs_source = cr_source.fetchall()
    for i in list(rs_source):
        v_col = v_col + "CAST(" + i[0] + " as char)," + "\'^^^\'" + ","
    cr_source.close()
    return 'CONCAT('+v_col[0:-7]+')'

def get_sync_table_pk_vals2(db,tab):
    cr_source  = db.cursor()
    v_col=''
    v_sql="""SELECT column_name FROM information_schema.`COLUMNS`
             WHERE table_schema=DATABASE()
               AND table_name='{0}' AND column_key='PRI'  ORDER BY ordinal_position
          """.format(tab)
    cr_source.execute(v_sql)
    rs_source = cr_source.fetchall()
    for i in list(rs_source):
        v_col = v_col +  i[0] + ","
    cr_source.close()
    return v_col[0:-1]

def get_sync_where(pk_cols,pk_vals):
    v_where=''
    for i in range(len(pk_cols.split(','))):
        v_where=v_where+pk_cols.split(',')[i]+"='"+pk_vals.split('^^^')[i]+"' and "
    return v_where[0:-4]

def get_sync_incr_max_rq(db,tab):
    cr_desc = db.cursor()
    v_tab   = tab.split(':')[0]
    v_rq    = tab.split(':')[1]
    if v_rq=='':
       return ''
    v_sql   = "select max({0}) from {1}".format(v_rq,v_tab)
    cr_desc.execute(v_sql)
    rs=cr_desc.fetchone()
    db.commit()
    cr_desc.close()
    return rs[0]

def get_sync_where_incr_mysql(tab,config):
    v_rq_col=tab.split(':')[1]
    v_expire_time=tab.split(':')[2]
    v = ''
    if config['sync_time_type']=='day':
       v = "where {0} >= DATE_SUB(NOW(),INTERVAL {1} DAY)".format(v_rq_col,v_expire_time)
    elif config['sync_time_type']=='hour':
       v = "where {0} >= DATE_SUB(NOW(),INTERVAL {1} HOUR)".format(v_rq_col, v_expire_time)
    elif config['sync_time_type'] == 'min':
       v = "where {0} >= DATE_SUB(NOW(),INTERVAL {1} MINUTE)".format(v_rq_col, v_expire_time)
    else:
       v = ''
    if tab.split(':')[1]=='':
       return ''
    else:
       return v

def get_sync_where_incr_mysql_rq(tab,config,currq):
    v_rq_col=tab.split(':')[1]
    v_expire_time=tab.split(':')[2]
    v = ''
    if config['sync_time_type'] == 'day':
        v = "where {0} >= DATE_SUB('{1}',INTERVAL {2} DAY)".format(v_rq_col,currq, v_expire_time)
    elif config['sync_time_type'] == 'hour':
        v = "where {0} >= DATE_SUB('{1}',INTERVAL {2} HOUR)".format(v_rq_col,currq, v_expire_time)
    elif config['sync_time_type'] == 'min':
        v = "where {0} >= DATE_SUB('{1}',INTERVAL {2} MINUTE)".format(v_rq_col,currq, v_expire_time)
    else:
        v = ''
    if tab.split(':')[1] == '':
        return ''
    else:
        return v

def get_md5(str):
    hash = hashlib.md5()
    hash.update(str.encode('utf-8'))
    return (hash.hexdigest())

def get_pk_vals_mysql(db,ftab,v_where):
    cr        = db.cursor()
    tab       = ftab.split(':')[0]
    v_pk_cols = get_sync_table_pk_vals(db, tab)
    v_sql     = "select {0} from {1} {2}".format(v_pk_cols, tab,v_where)
    cr.execute(v_sql)
    rs        = cr.fetchall()
    l_pk_vals = []
    for i in list(rs):
        l_pk_vals.append(i[0])
    cr.close()
    return l_pk_vals

def get_pk_vals_mysql2(db,ftab,v_where):
    cr        = db.cursor()
    tab       = ftab.split(':')[0]
    v_pk_cols = get_sync_table_pk_vals(db, tab)
    v_sql     = "select {0} from {1} {2}".format(v_pk_cols, tab,v_where)
    cr.execute(v_sql)
    rs        = cr.fetchall()
    v_pk_vals = ''
    for i in list(rs):
        v_pk_vals=v_pk_vals+"'"+i[0]+"',"
    cr.close()
    return v_pk_vals[0:-1]

def get_pk_vals_mysql3(rs):
    v_pk_vals=''
    for i in list(rs):
        v_pk_vals=v_pk_vals+"'"+i[0]+"',"
    return v_pk_vals[0:-1]

def get_pk_vals_incr(rs):
    l_pk_vals= []
    for i in list(rs):
        l_pk_vals.append(i[0])
    return l_pk_vals

def calc_pk_minus(mysql_desc,mysql_sour):
    minus = []
    for i in mysql_desc:
        if i not in mysql_sour:
            minus.append(i)
    return minus

def sync_incr_delete(config,ftab,v_where):
    db_sour    = config['db_mysql_sour']
    db_dest    = config['db_mysql_desc']
    cr_dest    = db_dest.cursor()
    tab        = ftab.split(':')[0]
    mysql_sour = get_pk_vals_mysql(db_sour,ftab,v_where)
    mysql_desc = get_pk_vals_mysql(db_dest,ftab,v_where)
    v_pk_names = get_sync_table_pk_names(db_sour, tab)
    minus      = calc_pk_minus(mysql_desc,mysql_sour)
    for i in minus:
        v_del="delete from {0} where {1}".format(tab,get_sync_where(v_pk_names,i))
        cr_dest.execute(v_del)
    print( "DB:{0},Table :{1} delete {2} rows!".format(config['db_mysql_desc_string'], tab, len(minus)))
    cr_dest.close()
    db_dest.commit()

def sync_mysql_init(config,debug):
    try:
        config_init={}
        for i in config['sync_table'].split(","):
            tab=i.split(':')[0]
            config_init[tab] = False
            if (check_mysql_tab_exists(config,tab)==0 \
                    or (check_mysql_tab_exists(config,tab)>0 and check_mysql_tab_sync(config,tab)==0)):

                #write init dict
                config_init[tab]=True

                #start first sync data
                i_counter        = 0
                ins_sql_header   = get_tab_header(config,tab)
                n_batch_size     = int(config['batch_size'])
                db_source        = config['db_mysql_sour']
                cr_source        = db_source.cursor()
                db_desc          = config['db_mysql_desc']
                cr_desc          = db_desc.cursor()

                print('delete table:{0} all data!'.format(tab))
                cr_desc.execute('delete from {0}'.format(tab))
                print('delete table:{0} all data ok!'.format(tab))

                n_tab_total_rows = get_sync_table_total_rows(db_source, tab, '')
                v_sql            = "select * from {0}".format(tab)
                cr_source.execute(v_sql)
                rs_source = cr_source.fetchmany(n_batch_size)
                while rs_source:
                    batch_sql =""
                    v_sql = ''
                    for i in range(len(rs_source)):
                        rs_source_desc = cr_source.description
                        ins_val = ""
                        for j in range(len(rs_source[i])):
                            col_type = str(rs_source_desc[j][1])
                            if  rs_source[i][j] is None:
                                ins_val = ins_val + "null,"
                            elif col_type == '253':  # varchar,date
                                ins_val = ins_val + "'"+ format_sql(str(rs_source[i][j])) + "',"
                            elif col_type in ('1', '3', '8', '246'):  # int,decimal
                                ins_val = ins_val + "'"+ str(rs_source[i][j]) + "',"
                            elif col_type == '12':  # datetime
                                ins_val = ins_val + "'"+ str(rs_source[i][j]).split('.')[0] + "',"
                            else:
                                ins_val = ins_val + "'"+ format_sql(str(rs_source[i][j])) + "',"
                        v_sql = v_sql +'('+ins_val[0:-1]+'),'
                    batch_sql = ins_sql_header + v_sql[0:-1]

                    #noinspection PyBroadException
                    # try:
                    #   cr_desc.execute(batch_sql)
                    #   i_counter = i_counter +len(rs_source)
                    # except:
                    #   print(traceback.format_exc())
                    #   print(batch_sql)
                    #   sys.exit(0)
                    config['run_sql'] = batch_sql
                    cr_desc.execute(batch_sql)
                    i_counter = i_counter + len(rs_source)


                    print("\rTable:{0},Total rec:{1},Process rec:{2},Complete:{3}%".
                          format(tab,n_tab_total_rows, i_counter, round(i_counter / n_tab_total_rows * 100,2)), end='')
                    if n_tab_total_rows == 0:
                        print("\rTable:{0},Total rec:{1},Process rec:{2},Complete:{3}%".
                              format(tab, n_tab_total_rows,i_counter,round(i_counter / 1 * 100,2)), end='')
                    else:
                        print("\rTable:{0},Total rec:{1},Process rec:{2},Complete:{3}%".
                              format(tab, n_tab_total_rows,i_counter, round(i_counter / n_tab_total_rows * 100, 2)), end='')

                    rs_source = cr_source.fetchmany(n_batch_size)
                db_desc.commit()
                print('')
        return config_init
    except Exception as e:
        print('sync_sqlserver_init exceptiion:' + traceback.format_exc())
        exception_running(config, traceback.format_exc())
        exit(0)


def sync_mysql_data(config,config_init):
    start_time = datetime.datetime.now()
    db=config['db_mysql_sour']
    amount=0
    for v in config['sync_table'].split(","):
        tab=v.split(':')[0]
        if get_sync_table_pk_names(db,tab)=='pkid':
           sync_mysql_data_pkid(config, v,config_init)
        else:
           sync_mysql_data_no_pkid(config,v,config_init)

        if config['run_mode'] == 'remote':
           amount = amount + int(config['sync_amount'])

    if config['run_mode'] == 'remote':
       #write write_sync_log_detail
       config['sync_amount']   = str(amount)
       config['sync_duration'] = str(get_seconds(start_time))
       write_sync_log(config)


def sync_mysql_data_no_pkid(config, ftab,config_init):
    try:
        #start sync dml data
        config['sync_amount'] = 0
        if not check_full_sync(config, ftab.split(':')[0],config_init):
            i_counter        = 0
            i_counter_upd    = 0
            tab              = ftab.split(':')[0]
            db_source3       = config['db_mysql_sour3']
            db_desc3         = config['db_mysql_desc3']
            v_maxrq          = get_sync_incr_max_rq(db_desc3, ftab)
            v_where          = get_sync_where_incr_mysql(ftab, config)
            ins_sql_header   = get_tab_header(config, tab)
            n_batch_size     = int(config['batch_size_incr'])
            db_source        = config['db_mysql_sour']
            db_source2       = config['db_mysql_sour2']
            cr_source        = db_source.cursor()
            cr_source2       = db_source2.cursor()
            db_desc          = config['db_mysql_desc']
            v_pk_names       = get_sync_table_pk_names(db_source, tab)
            v_pk_cols        = get_sync_table_pk_vals(db_source, tab)
            cr_desc          = db_desc.cursor()
            n_tab_total_rows = get_sync_table_total_rows(db_source, tab, v_where)
            v_sql            = """select {0} as 'pk',{1} from {2} {3}""".format(v_pk_cols, get_sync_table_cols(db_source, tab), tab, v_where)
            n_rows           = 0
            cr_source.execute(v_sql)
            rs_source  = cr_source.fetchmany(n_batch_size)
            start_time = datetime.datetime.now()

            if ftab.split(':')[1] == '':
                print( "Sync Table increment :{0} ...".format(ftab.split(':')[0]))
            else:
                print( "Sync Table increment :{0} for In recent {1} {2}..."
                       .format(ftab.split(':')[0],ftab.split(':')[2],config['sync_time_type']))

            if ftab.split(':')[1] == '':
               print('DB:{0},delete {1} table data please wait...'.format(config['db_mysql_desc_string'], tab,ftab.split(':')[2]))
               cr_desc.execute('delete from {0}'.format(tab))
               print('DB:{0},delete {1} table data ok!'.format(config['db_mysql_desc_string'], tab))

            while rs_source:
                batch_sql = ""
                batch_sql_del=""
                v_sql = ''
                v_sql_del = ''
                for r in list(rs_source):
                    rs_source_desc = cr_source.description
                    ins_val = ""
                    for j in range(1,len(r)):
                        col_type = str(rs_source_desc[j][1])
                        if r[j] is None:
                            ins_val = ins_val + "null,"
                        elif col_type == '253':  # varchar,date
                            ins_val = ins_val + "'" + format_sql(str(r[j])) + "',"
                        elif col_type in ('1', '3', '8', '246'):  # int,decimal
                            ins_val = ins_val + "'" + str(r[j]) + "',"
                        elif col_type == '12':  # datetime
                            ins_val = ins_val + "'" + str(r[j]).split('.')[0] + "',"
                        else:
                            ins_val = ins_val + "'" + format_sql(str(r[j])) + "',"
                    v_sql = v_sql + '(' + ins_val[0:-1] + '),'
                    v_sql_del = v_sql_del + get_sync_where(v_pk_names, r[0])+ ","
                batch_sql = ins_sql_header + v_sql[0:-1]

                #noinspection PyBroadException
                # try:
                #     if ftab.split(':')[1] == '':
                #         cr_desc.execute(batch_sql)
                #     else:
                #         for d in v_sql_del[0:-1].split(','):
                #             cr_desc.execute('delete from {0} where {1}'.format(tab, d))
                #         cr_desc.execute(batch_sql)
                #     i_counter = i_counter + len(rs_source)
                # except:
                #     print(traceback.format_exc())
                #     print(batch_sql)
                #     sys.exit(0)

                if ftab.split(':')[1] == '':
                    config['run_sql'] =batch_sql
                    cr_desc.execute(batch_sql)
                else:
                    for d in v_sql_del[0:-1].split(','):
                        config['run_sql'] = 'delete from {0} where {1}'.format(tab, d)
                        cr_desc.execute('delete from {0} where {1}'.format(tab, d))
                    config['run_sql'] = batch_sql
                    cr_desc.execute(batch_sql)
                i_counter = i_counter + len(rs_source)


                print("\rTable:{0},Total rec:{1},Process rec:{2},Complete:{3}%"
                      .format(tab, n_tab_total_rows, i_counter, round(i_counter / n_tab_total_rows * 100, 2)), end='')
                if n_tab_total_rows == 0:
                    print( "\rTable:{0},Total rec:{1},Process rec:{2},Complete:{3}%"
                          .format(tab, n_tab_total_rows, i_counter, round(i_counter / 1 * 100, 2)), end='')
                else:
                    print( "\rTable:{0},Total rec:{1},Process rec:{2},Complete:{3}%"
                           .format(tab, n_tab_total_rows, i_counter, round(i_counter / n_tab_total_rows * 100, 2)), end='')
                rs_source = cr_source.fetchmany(n_batch_size)
            print('')
            db_desc.commit()
            if config['run_mode'] == 'remote':
               #write write_sync_log_detail
               config['sync_duration'] = str(get_seconds(start_time))
               config['sync_table_inteface'] = tab
               config['sync_amount'] = str(i_counter)
               write_sync_log_detail(config)
    except Exception as e:
        print('sync_sqlserver_data_pk exceptiion:' + traceback.format_exc())
        exception_running(config, traceback.format_exc())
        exit(0)

def sync_mysql_data_pkid(config, ftab,config_init):
    try:
        #start sync dml
        config['sync_amount'] = 0
        if not check_full_sync(config, ftab.split(':')[0],config_init):
            i_counter        = 0
            tab              = ftab.split(':')[0]
            db_source3       = config['db_mysql_sour3']
            db_desc3         = config['db_mysql_desc3']
            v_maxrq          = get_sync_incr_max_rq(db_desc3, ftab)
            v_where          = get_sync_where_incr_mysql(ftab, config)
            ins_sql_header   = get_tab_header_pkid(config, tab)
            ins_sql_cols     = get_sync_table_cols_pkid(db_source3,tab)
            n_batch_size     = int(config['batch_size_incr'])
            db_source        = config['db_mysql_sour']
            db_source2       = config['db_mysql_sour2']
            cr_source        = db_source.cursor()
            cr_source2       = db_source2.cursor()
            db_desc          = config['db_mysql_desc']
            v_pk_names       = get_sync_table_pk_names(db_source, tab)
            v_pk_cols        = get_sync_table_pk_vals(db_source, tab)
            cr_desc          = db_desc.cursor()
            n_tab_total_rows = get_sync_table_total_rows(db_source, tab, v_where)
            v_sql            = """select {0} from {1} {2}""".format(ins_sql_cols,tab, v_where)
            n_rows           = 0
            cr_source.execute(v_sql)
            rs_source  = cr_source.fetchmany(n_batch_size)
            start_time = datetime.datetime.now()
            if ftab.split(':')[1] == '':
                print( "Sync Table increment :{0} ...".format(ftab.split(':')[0]))
            else:
                print( "Sync Table increment :{0} for In recent {1} {2}..."
                                  .format(ftab.split(':')[0],ftab.split(':')[2],config['sync_time_type']))

            cr_desc.execute('delete from {0} {1} '.format(tab, v_where))
            print('DB:{0},delete {1} table recent {2} data...'.format(config['db_mysql_desc_string'],tab,ftab.split(':')[2]))

            while rs_source:
                batch_sql = ""
                v_sql = ''
                for i in range(len(rs_source)):
                    rs_source_desc = cr_source.description
                    ins_val = ""
                    for j in range(len(rs_source[i])):
                        col_type = str(rs_source_desc[j][1])
                        if rs_source[i][j] is None:
                            ins_val = ins_val + "null,"
                        elif col_type == '253':  # varchar,date
                            ins_val = ins_val + "'" + format_sql(str(rs_source[i][j])) + "',"
                        elif col_type in ('1', '3', '8', '246'):  # int,decimal
                            ins_val = ins_val + "'" + str(rs_source[i][j]) + "',"
                        elif col_type == '12':  # datetime
                            ins_val = ins_val + "'" + str(rs_source[i][j]).split('.')[0] + "',"
                        else:
                            ins_val = ins_val + "'" + format_sql(str(rs_source[i][j])) + "',"
                    v_sql = v_sql + '(' + ins_val[0:-1] + '),'
                batch_sql = ins_sql_header + v_sql[0:-1]
                # noinspection PyBroadException
                # try:
                #     cr_desc.execute(batch_sql)
                #     i_counter = i_counter + len(rs_source)
                # except:
                #     print(traceback.format_exc())
                #     print(batch_sql)
                #     sys.exit(0)

                config['run_sql'] = batch_sql
                cr_desc.execute(batch_sql)
                i_counter = i_counter + len(rs_source)

                print("\rTable:{0},Total rec:{1},Process rec:{2},Complete:{3}%"
                      .format(tab, n_tab_total_rows, i_counter, round(i_counter / n_tab_total_rows * 100, 2)), end='')
                if n_tab_total_rows == 0:
                    print("\rTable:{0},Total rec:{1},Process rec:{2},Complete:{3}%"
                           .format(tab, n_tab_total_rows, i_counter, round(i_counter / 1 * 100, 2)), end='')
                else:
                    print("\rTable:{0},Total rec:{1},Process rec:{2},Complete:{3}%"
                           .format(tab, n_tab_total_rows, i_counter, round(i_counter / n_tab_total_rows * 100, 2)), end='')
                rs_source = cr_source.fetchmany(n_batch_size)
            print('')
            db_desc.commit()
            if config['run_mode'] == 'remote':
               #write write_sync_log_detail
               config['sync_duration'] = str(get_seconds(start_time))
               config['sync_table_inteface'] = tab
               config['sync_amount'] = str(i_counter)
               write_sync_log_detail(config)
    except Exception as e :
        print('sync_mysql_data_pkid exceptiion:' + traceback.format_exc())
        exception_running(config, traceback.format_exc())
        exit(0)


def check_full_sync(config,tab,config_init):
    #if check_mysql_tab_exists_pk(config, tab) == 0 or config_init[tab]:
    if check_mysql_tab_exists_pk(config,tab)==0 :
       return True
    else:
       return False

def cleaning_table(config):
    print('starting cleaning_table please wait...')
    db   = config['db_mysql_desc3']
    cr   = db.cursor()
    desc = config['db_mysql_desc_string']
    start_time = datetime.datetime.now()
    #如果索引不存在，则建立索引
    v_chk_idx_sql="SELECT count(0) FROM information_schema.innodb_sys_indexes WHERE NAME='idx_tc_recordarchive_n1'"
    v_cre_idx_sql="CREATE INDEX idx_tc_recordarchive_n1 ON tc_recordarchive(intime,carno,pkid)"

    #表数据去重
    n_cnt_rep_sql = 0
    v_cnt_rep_sql = """select count(0) from tc_recordarchive
                          where pkid in(select pkid from (select  max(pkid) AS pkid from tc_recordarchive 
                                         where indeviceentrytype=1
                                           group by carno,intime having count(0)>1) t)"""

    v_del_rep_sql="""delete from tc_recordarchive
                      where pkid in(select pkid from (select  max(pkid) AS pkid from tc_recordarchive 
                                     where indeviceentrytype=1
                                       group by carno,intime having count(0)>1) t)"""
    for i in config['sync_table'].split(","):
        tab = i.split(':')[0]
        if tab=="tc_recordarchive":
           #创建索引
           print('DB:{0} cleaning table tc_recordarchive create index...'.format(desc))
           cr.execute(v_chk_idx_sql)
           rs = cr.fetchone()
           if rs[0]==0:
              print('DB:{0},createing index idx_tc_recordarchive_n1 for {1} please wait...'.format(desc,tab))
              cr.execute(v_cre_idx_sql)
              print('DB:{0},Table:{1} index idx_tc_recordarchive_n1 create complete!'.format(desc,tab))
           else:
              print('DB:{0} cleaning table tc_recordarchive index idx_tc_recordarchive_n1 already exists!')

           #删除重复数据
           print('DB:{0} cleaning table tc_recordarchive delete repeat data...'.format(desc))
           cr.execute(v_cnt_rep_sql)
           rs=cr.fetchone()
           if rs[0]>0:
             print('DB:{0},deleting table {1} repeat data please wait...'.format(desc,tab))
             cr.execute(v_del_rep_sql)
             print('DB:{0},Table:{1} delete repeat data {2} rows!'.format(desc,tab,rs[0]))
           else:
             print('DB:{0} cleaning table tc_recordarchive no repeat data!'.format(desc))

    db.commit()
    cr.close()
    print('complete cleaning_table,elaspse:{0}s'.format(str(get_seconds(start_time))))

def cleaning_park(config):
    db   = config['db_mysql_desc3']
    cr   = db.cursor()
    desc = config['db_mysql_desc_string']
    start_time = datetime.datetime.now()
    #调用过程进行数据清洗
    if config['sync_table'].count('tc_record')>0 and config['sync_table'].count('tc_recordarchive'):
        print("cleaning park data please wait...")
        cr.callproc('proc_park_cleaning')
        print("cleaning park data...ok".format(str(get_seconds(start_time))))
        db.commit()
        cr.close()
        print('complete cleaning_park data complete,elaspse:{0}s'.format(str(get_seconds(start_time))))

def write_local_config_file(config):
    sync_db_sour=config['db_mysql_sour_ip']+':'+\
                 config['db_mysql_sour_port']+':'+\
                 config['db_mysql_sour_service']+':'+\
                 config['db_mysql_sour_user']+':'+\
                 config['db_mysql_sour_pass']

    sync_db_dest=config['db_mysql_desc_ip']+':'+\
                 config['db_mysql_desc_port']+':'+\
                 config['db_mysql_desc_service']+':'+\
                 config['db_mysql_desc_user']+':'+\
                 config['db_mysql_desc_pass']

    file_name   = config['script_path']+'/config/'+config['sync_tag']+'.ini'
    file_handle = open(file_name, 'w')
    file_handle.write('[sync]' + '\n')
    file_handle.write('sync_db_mysql_sour={0}\n'.format(sync_db_sour))
    file_handle.write('sync_db_mysql_desc={0}\n'.format(sync_db_dest))
    file_handle.write('sync_table={0}\n'.format(config['sync_table']))
    file_handle.write('sync_col_name={0}\n'.format(config['sync_col_name']))
    file_handle.write('sync_col_val={0}\n'.format(config['sync_col_val']))
    file_handle.write('batch_size={0}\n'.format(config['batch_size']))
    file_handle.write('batch_size_incr={0}\n'.format(config['batch_size_incr']))
    file_handle.write('sync_time_type={0}\n'.format(config['sync_time_type']))
    file_handle.write('sync_gap={0}\n'.format(config['sync_gap']))
    file_handle.close()
    print("{0} export complete!".format(file_name))


def init(config,debug,workdir):
    config = get_config_from_db(config,workdir)

    if debug:
       print_dict(config)
    return config

def exception_connect_db(config,p_error):
    v_templete = '''
        <html>
           <head>
              <style type="text/css">
                  .xwtable {width: 100%;border-collapse: collapse;border: 1px solid #ccc;}
                  .xwtable thead td {font-size: 12px;color: #333333;
                                     text-align: center;background: url(table_top.jpg) repeat-x top center;
                                     border: 1px solid #ccc; font-weight:bold;}
                  .xwtable thead th {font-size: 12px;color: #333333;
                                     text-align: center;background: url(table_top.jpg) repeat-x top center;
                                     border: 1px solid #ccc; font-weight:bold;}
                  .xwtable tbody tr {background: #fff;font-size: 12px;color: #666666;}
                  .xwtable tbody tr.alt-row {background: #f2f7fc;}
                  .xwtable td{line-height:20px;text-align: left;padding:4px 10px 3px 10px;height: 18px;border: 1px solid #ccc;}
              </style>
           </head>
           <body>             
              <table class='xwtable'>
                  <tr><td  width="30%">任务描述</td><td  width="70%">$$task_desc$$</td></tr>
                  <tr><td>任务标识</td><td>$$sync_tag$$</td></tr>                 
                  <tr><td>业务类型</td><td>$$sync_ywlx$$</td></tr>
                  <tr><td>同步方向</td><td>$$sync_type$$</td></tr>
                  <tr><td>同步服务器</td><td>$$server_id$$</td></tr>
                  <tr><td>源数据源</td><td>$$sync_db_sour$$</td></tr>
                  <tr><td>目标数据源</td><td>$$sync_db_dest$$</td></tr>
                  <tr><td>同步表名</td><td>$$sync_table$$</td></tr>
                  <tr><td>时间类型</td><td>$$sync_time_type$$</td></tr>
                  <tr><td>同步脚本</td><td>$$script_file$$</td></tr>
                  <tr><td>运行时间</td><td>$$run_time$$</td></tr>                
                  <tr><td>异常信息</td><td>$$run_error$$</td></tr>
              </table>                
           </body>
        </html>
       '''
    v_title  = '数据同步数据库异常[★★★]'
    v_content = v_templete.replace('$$task_desc$$', config.get('comments'))
    v_content = v_content.replace('$$sync_tag$$',   config.get('sync_tag'))
    v_content = v_content.replace('$$sync_ywlx$$' , config.get('sync_ywlx_name'))
    v_content = v_content.replace('$$sync_type$$' , config.get('sync_type_name'))
    v_content = v_content.replace('$$server_id$$', str(config.get('server_desc')))
    v_content = v_content.replace('$$sync_db_sour$$', config.get('sync_db_sour'))
    v_content = v_content.replace('$$sync_db_dest$$', config.get('sync_db_dest'))
    v_content = v_content.replace('$$sync_table$$', config.get('sync_table'))
    v_content = v_content.replace('$$sync_time_type$$', config.get('sync_time_type_name'))
    v_content = v_content.replace('$$script_file$$', config.get('script_file'))
    v_content = v_content.replace('$$run_time$$', config.get('run_time'))
    v_content = v_content.replace('$$run_error$$', str(p_error))
    send_mail25('190343@lifeat.cn','Hhc5HBtAuYTPGHQ8','190343@lifeat.cn', v_title,v_content)

def exception_interface(v_title,v_content):
    v_templete = '''
           <html>
              <head>
                 <style type="text/css">
                     .xwtable {width: 100%;border-collapse: collapse;border: 1px solid #ccc;}
                     .xwtable thead td {font-size: 12px;color: #333333;
                                        text-align: center;background: url(table_top.jpg) repeat-x top center;
                                        border: 1px solid #ccc; font-weight:bold;}
                     .xwtable thead th {font-size: 12px;color: #333333;
                                        text-align: center;background: url(table_top.jpg) repeat-x top center;
                                        border: 1px solid #ccc; font-weight:bold;}
                     .xwtable tbody tr {background: #fff;font-size: 12px;color: #666666;}
                     .xwtable tbody tr.alt-row {background: #f2f7fc;}
                     .xwtable td{line-height:20px;text-align: left;padding:4px 10px 3px 10px;height: 18px;border: 1px solid #ccc;}
                 </style>
              </head>
              <body>             
                 $$TABLE$$           
              </body>
           </html>
          '''
    v_templete = v_templete.replace('$$TABLE$$',v_content)
    send_mail25('190343@lifeat.cn','Hhc5HBtAuYTPGHQ8','190343@lifeat.cn', v_title,v_templete)

def exception_running(config,p_error):
    v_templete = '''
     <html>
        <head>
           <style type="text/css">
               .xwtable {width: 100%;border-collapse: collapse;border: 1px solid #ccc;}
               .xwtable thead td {font-size: 12px;color: #333333;
                                  text-align: center;background: url(table_top.jpg) repeat-x top center;
                                  border: 1px solid #ccc; font-weight:bold;}
               .xwtable thead th {font-size: 12px;color: #333333;
                                  text-align: center;background: url(table_top.jpg) repeat-x top center;
                                  border: 1px solid #ccc; font-weight:bold;}
               .xwtable tbody tr {background: #fff;font-size: 12px;color: #666666;}
               .xwtable tbody tr.alt-row {background: #f2f7fc;}
               .xwtable td{line-height:20px;text-align: left;padding:4px 10px 3px 10px;height: 18px;border: 1px solid #ccc;}
           </style>
        </head>
        <body>             
           <table class='xwtable'>
               <tr><td  width="30%">任务描述</td><td  width="70%">$$task_desc$$</td></tr>
               <tr><td>任务标识</td><td>$$sync_tag$$</td></tr>
               <tr><td>业务类型</td><td>$$sync_ywlx$$</td></tr>
               <tr><td>同步方向</td><td>$$sync_type$$</td></tr>
               <tr><td>同步服务器</td><td>$$server_id$$</td></tr>
               <tr><td>源数据源</td><td>$$sync_db_sour$$</td></tr>
               <tr><td>目标数据源</td><td>$$sync_db_dest$$</td></tr>
               <tr><td>同步表名</td><td>$$sync_table$$</td></tr>
               <tr><td>时间类型</td><td>$$sync_time_type$$</td></tr>
               <tr><td>同步脚本</td><td>$$script_file$$</td></tr>
               <tr><td>运行时间</td><td>$$run_time$$</td></tr>
               <tr><td>运行语句</td><td>$$run_sql$$</td></tr>
               <tr><td>异常信息</td><td>$$run_error$$</td></tr>
           </table>                
        </body>
     </html>
    '''

    v_title   = '数据同步运行异常[★★★]'
    v_content = v_templete.replace('$$task_desc$$'    ,config.get('comments'))
    v_content = v_content.replace('$$sync_tag$$'      ,config.get('sync_tag'))
    v_content = v_content.replace('$$sync_ywlx$$'     ,config.get('sync_ywlx_name'))
    v_content = v_content.replace('$$sync_type$$'     ,config.get('sync_type_name'))
    v_content = v_content.replace('$$server_id$$'     ,str(config.get('server_desc')))
    v_content = v_content.replace('$$sync_db_sour$$'  ,config.get('sync_db_sour'))
    v_content = v_content.replace('$$sync_db_dest$$'  ,config.get('sync_db_dest'))
    v_content = v_content.replace('$$sync_table$$'    ,config.get('sync_table'))
    v_content = v_content.replace('$$sync_time_type$$',config.get('sync_time_type_name'))
    v_content = v_content.replace('$$script_file$$'  , config.get('script_file'))
    v_content = v_content.replace('$$run_time$$'      ,config.get('run_time'))
    v_content = v_content.replace('$$run_sql$$'       ,config.get('run_sql'))
    v_content = v_content.replace('$$run_error$$'     ,str(p_error))

    send_mail25('190343@lifeat.cn','Hhc5HBtAuYTPGHQ8','190343@lifeat.cn', v_title,v_content)


def sync(config,debug):

    #sync table ddl
    sync_mysql_ddl(config, debug)

    #init sync table
    config_init=sync_mysql_init(config, debug)

    #sync data
    while True:
      #sync increment data
      sync_mysql_data(config,config_init)

      #clearing desc table
      cleaning_park(config)

      sys.exit(0)

def main():
    #init variable
    config = ""
    debug = False
    check = False
    warnings.filterwarnings("ignore")
    #get parameter from console
    for p in range(len(sys.argv)):
        if sys.argv[p] == "-tag":
            config = sys.argv[p + 1]
        elif sys.argv[p] == "-workdir":
            workdir = sys.argv[p + 1]
        elif sys.argv[p] == "-debug":
            debug = True

    #初始化
    config=init(config,debug,workdir)

    #数据同步
    sync(config, debug)

if __name__ == "__main__":
     main()
