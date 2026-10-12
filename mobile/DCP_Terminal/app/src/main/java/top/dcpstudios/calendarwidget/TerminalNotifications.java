package top.dcpstudios.calendarwidget;

import android.app.*;import android.content.*;import android.content.pm.PackageManager;import android.os.Build;import org.json.JSONObject;

final class TerminalNotifications {
    static void channels(Context c){if(Build.VERSION.SDK_INT>=26){NotificationManager m=c.getSystemService(NotificationManager.class);
        m.createNotificationChannel(new NotificationChannel("terminal_connection","消息通道运行状态",NotificationManager.IMPORTANCE_LOW));
        m.createNotificationChannel(new NotificationChannel("terminal_wechat","微信新消息",NotificationManager.IMPORTANCE_HIGH));
        m.createNotificationChannel(new NotificationChannel("terminal_canvas","Canvas 新作业",NotificationManager.IMPORTANCE_HIGH));
        m.createNotificationChannel(new NotificationChannel("terminal_schedule","个人日程与服务通知",NotificationManager.IMPORTANCE_HIGH));}}
    static Notification.Builder builder(Context c,String channel){return Build.VERSION.SDK_INT>=26?new Notification.Builder(c,channel):new Notification.Builder(c);}
    static PendingIntent open(Context c,int id){return PendingIntent.getActivity(c,id,new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra("messageId",(long)id).putExtra("page","messages"),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
    static void show(Context c,JSONObject msg){if(Build.VERSION.SDK_INT>=33&&c.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)return;
        channels(c);String source=msg.optString("source"),channel="wechat".equals(source)?"terminal_wechat":"canvas".equals(source)?"terminal_canvas":"terminal_schedule";
        if(!TerminalClient.prefs(c).getBoolean("notify_"+source,true))return;int id=msg.optInt("id");
        Notification n=builder(c,channel).setSmallIcon(R.drawable.ic_terminal_notification).setContentTitle(msg.optString("title")).setContentText(msg.optString("body")).setStyle(new Notification.BigTextStyle().bigText(msg.optString("body"))).setContentIntent(open(c,id)).setAutoCancel(true).setVisibility(Notification.VISIBILITY_PRIVATE).setCategory(Notification.CATEGORY_MESSAGE).build();
        ((NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE)).notify(id+1000,n);
    }
}
