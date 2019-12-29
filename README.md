一、概述  

   数据库API-Server基本python3.6开发，使用tornado后端框架。 
   
   平台功能： 为数据库自动化平台备份及同步提供API接口服务。
   
  1.1 备份接口：

------------

|  接口	 |描述   |
| :------------ | :------------ |
| /read_config_backup    | 获取备份任务配置信息，入口：备份标识号 |
| /read_db_decrypt       | 获取数据库密码，入口：加密密文，密钥  |
| /update_backup_status  | 更新数据库备份任务运行状态  |
| /write_backup_total    | 写备份任务汇总信息   |
| /write_backup_detail   | 写备份任务明细信息   |
| /set_crontab_local     | 配置本地crontab任务  |
| /set_crontab_remote    | 配置远程crontab任务  |
| /push_script_remote    | 推送最新备份客户端至远程，同时根据最新配置设置定时任务   |
| /run_script_remote     | 运行远程备份任务  |
| /stop_script_remote    | 停止远程备份任务  |


  1.2 同步接口：

------------

|  接口	 |描述   |
| :------------ | :------------ |
| /read_config_sync         | 获取同步任务配置信息，入口：同步标识号 |
| /push_script_remote_sync  | 推送最新同步客户端至远程，同时根据最新配置设置定时任务  |
| /write_sync_log           | 写同步任务汇总信息  |
| /write_sync_log_detail    | 写同步任务明细信息   |
| /run_script_remote_sync   | 运行远程同步任务   |
| /stop_script_remote_sync  | 停止远程同步任务  |

       
二、安装部署  

2.1 安装依赖

pip install tornado  

pip install pymysql  

pip install paramiko  

pip install crontab


三、停启服务

3.1 启动服务  

more startup.sh  

export PYTHON3_HOME=/usr/local/python3.6  

export LD_LIBRARY_PATH=${PYTHON3_HOME}/lib  

nohup $PYTHON3_HOME/bin/python3 /home/hopson/apps/usr/webserver/dbapi/dbapi.py $1 &


3.2 重启服务  

more restart.sh  

/home/hopson/apps/usr/webserver/dbapi/stop.sh  

/home/hopson/apps/usr/webserver/dbapi/start.sh 8181  

/home/hopson/apps/usr/webserver/dbapi/start.sh 8182  

/home/hopson/apps/usr/webserver/dbapi/start.sh 8183  

/home/hopson/apps/usr/webserver/dbapi/start.sh 8184  

/home/hopson/apps/usr/webserver/dbapi/start.sh 8185  

/home/hopson/apps/usr/webserver/dbapi/start.sh 8186  

/home/hopson/apps/usr/webserver/dbapi/start.sh 8187  

/home/hopson/apps/usr/webserver/dbapi/start.sh 8188  


3.3 停止服务  

more stop.sh  

ps -ef |grep dbapi |awk '{print $2}' | xargs kill -9  


3.4 nginx配置  

详见：http://www.zhitbar.com/4177.html

dbapi :80端口  


3.5 启动nginx  

 启动：/usr/sbin/nginx/nginx  
 
 关闭：/usr/sbin/nginx/nginx -s 
 
 重启：/usr/sbin/nginx/nginx -s  reload 