package top.dcpstudios.calendarwidget;

import android.app.*;import android.content.*;import android.os.*;import java.io.*;import java.net.*;import org.json.*;

/** Explicitly enabled persistent personal inbox connection with durable reconnect replay. */
public class TerminalService extends Service {
    volatile boolean running;volatile HttpURLConnection connection;Thread worker;
    public static void enable(Context c,boolean enabled){TerminalClient.prefs(c).edit().putBoolean("notifications",enabled).commit();Intent i=new Intent(c,TerminalService.class);if(enabled){if(Build.VERSION.SDK_INT>=26)c.startForegroundService(i);else c.startService(i);}else c.stopService(i);}
    public int onStartCommand(Intent i,int flags,int startId){
        if(i!=null&&"STOP".equals(i.getAction())){TerminalClient.prefs(this).edit().putBoolean("notifications",false).commit();stopSelf();return START_NOT_STICKY;}
        if(!TerminalClient.prefs(this).getBoolean("notifications",false)){stopSelf();return START_NOT_STICKY;}
        TerminalNotifications.channels(this);showConnection("个人消息同步服务运行中");
        if(worker==null){running=true;worker=new Thread(this::listen,"terminal-stream");worker.start();}return START_STICKY;
    }
    void showConnection(String state){
        Intent stop=new Intent(this,TerminalService.class).setAction("STOP");PendingIntent pause=PendingIntent.getService(this,777,stop,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder=TerminalNotifications.builder(this,"terminal_connection").setSmallIcon(R.drawable.ic_terminal_notification).setContentTitle("DCP Terminal").setContentText("个人消息同步服务运行中").setOnlyAlertOnce(true).setOngoing(true).setContentIntent(TerminalNotifications.open(this,0)).addAction(android.R.drawable.ic_media_pause,"暂停",pause);
        builder.setSound(null).setVibrate(null).setDefaults(0);
        startForeground(8,builder.build());
    }
    void listen(){int failures=0;
        while(running){try{
            TerminalClient.sync(this,true);
            if(!NetDiskSession.canTerminal(this)){new Handler(getMainLooper()).post(()->{if(running)showConnection("同步当前账号的网盘日程");});Thread.sleep(30000);continue;}
            NetDiskSession.AuthorizedConnection stream=NetDiskSession.openBound(this,"/api/mobile/terminal/stream?after="+TerminalClient.prefs(this).getLong("cursor",0),"GET",null);
            connection=stream.connection;connection.setRequestProperty("Accept","text/event-stream");connection.setReadTimeout(40000);
            if(connection.getResponseCode()!=200)throw new IOException("消息通道 HTTP "+connection.getResponseCode());
            failures=0;new Handler(getMainLooper()).post(()->{if(running)showConnection("实时接收微信与 Canvas 消息");});
            long lastPolicy=0;try(BufferedReader in=new BufferedReader(new InputStreamReader(connection.getInputStream(),java.nio.charset.StandardCharsets.UTF_8))){String line;while(running&&(line=in.readLine())!=null){if(line.startsWith("data: ")){JSONObject m=new JSONObject(line.substring(6));TerminalClient.receive(this,m,true,stream.account);if("schedule".equals(m.optString("source")))TerminalClient.refresh(this,()->{});}if(System.currentTimeMillis()-lastPolicy>30000){lastPolicy=System.currentTimeMillis();AttentionSettings.cache(this,TerminalClient.requestBound(this,"/attention",null,stream.account));CalendarWidget.renderAll(this);}}}
        }catch(Exception e){if(running){android.content.SharedPreferences prefs=TerminalClient.prefs(this);prefs.edit().putString("error","消息通道重连中").putLong("error_since",prefs.getLong("error_since",System.currentTimeMillis())).apply();}}
        finally{if(connection!=null){connection.disconnect();connection=null;}}
        if(running)try{Thread.sleep(Math.min(60000,3000L*(1L<<Math.min(failures++,4))));}catch(InterruptedException ignored){}
        }
    }
    public void onDestroy(){running=false;if(connection!=null)connection.disconnect();if(worker!=null)worker.interrupt();super.onDestroy();}
    public IBinder onBind(Intent intent){return null;}
}
