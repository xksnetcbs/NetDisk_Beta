package top.dcpstudios.calendarwidget;
import android.app.*;import android.appwidget.*;import android.content.*;import android.net.Uri;import android.os.Bundle;import android.os.Build;import android.widget.*;
public class CalendarWidget extends AppWidgetProvider {
 static final String REFRESH="top.dcpstudios.calendarwidget.REFRESH";
 static final android.os.Handler CARD_TIMER=new android.os.Handler(android.os.Looper.getMainLooper());static Runnable expiry;
 public void onUpdate(Context c,AppWidgetManager m,int[] ids){renderAll(c);SyncJobService.schedule(c,true);}
 public void onAppWidgetOptionsChanged(Context c,AppWidgetManager m,int id,Bundle options){render(c.getApplicationContext(),AppWidgetManager.getInstance(c.getApplicationContext()),id);}
 public void onReceive(Context c,Intent i){super.onReceive(c,i);if("DCP_ARRIVED".equals(i.getAction())){TerminalClient.prefs(c).edit().putString("arrived",i.getStringExtra("arrival")).apply();renderAll(c);return;}if("DCP_CARD_TICK".equals(i.getAction())){renderAll(c);return;}if((Intent.ACTION_BOOT_COMPLETED.equals(i.getAction())||Intent.ACTION_MY_PACKAGE_REPLACED.equals(i.getAction()))&&TerminalClient.prefs(c).getBoolean("notifications",false)){try{TerminalService.enable(c,true);}catch(RuntimeException e){TerminalClient.prefs(c).edit().putString("error","请打开 APP 恢复实时消息通知").apply();}}if(REFRESH.equals(i.getAction())||Intent.ACTION_BOOT_COMPLETED.equals(i.getAction())||Intent.ACTION_MY_PACKAGE_REPLACED.equals(i.getAction())){renderAll(c);SyncJobService.schedule(c,true);}}
 public static synchronized void renderAll(Context c){final Context app=c.getApplicationContext();AppWidgetManager m=AppWidgetManager.getInstance(app);int[] ids=m.getAppWidgetIds(new ComponentName(app,CalendarWidget.class));for(int id:ids)render(app,m,id);if(expiry!=null)CARD_TIMER.removeCallbacks(expiry);long now=System.currentTimeMillis(),until=AttentionSettings.state(app).optLong("summary_until");if(ids.length>0){long next=until>now?Math.min(now+60000,until):now+60000;AlarmManager alarm=(AlarmManager)app.getSystemService(Context.ALARM_SERVICE);alarm.set(AlarmManager.RTC,next,PendingIntent.getBroadcast(app,3300,new Intent(app,CalendarWidget.class).setAction("DCP_CARD_TICK"),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE));if(until>now){expiry=()->renderAll(app);CARD_TIMER.postDelayed(expiry,until-now);}}}
 static void render(Context c,AppWidgetManager m,int id){
  RemoteViews deck=new RemoteViews(c.getPackageName(),R.layout.widget_deck_scrollable);configureTodo(c,deck,id);
  // The todo list is a permanent XML child. Rebuild only the reminder overlay,
  // so periodic updates keep the host's list and scroll position intact.
  deck.removeAllViews(R.id.card_flipper);deck.addView(R.id.card_flipper,new RemoteViews(c.getPackageName(),R.layout.widget_blank));int i=0;
  for(AttentionCards.Card card:AttentionCards.cards(c)){if("todo".equals(card.id)||(!card.uid.isEmpty()&&card.message==0))continue;deck.addView(R.id.card_flipper,AttentionCards.view(c,card,20000+id*20+i++));}
  bindTodoList(c,deck,id);m.updateAppWidget(id,deck);if(Build.VERSION.SDK_INT<31)m.notifyAppWidgetViewDataChanged(id,R.id.widget_list);
 }
 static RemoteViews todoViews(Context c,int id){
  RemoteViews v=new RemoteViews(c.getPackageName(),R.layout.widget_scrollable);configureTodo(c,v,id);return v;
 }
 static void configureTodo(Context c,RemoteViews v,int id){
  v.setTextViewText(R.id.widget_status,CalendarStore.status(c));
  v.setInt(R.id.todo_root,"setBackgroundResource",AttentionCards.dark(c)?R.drawable.attention_background_dark:R.drawable.attention_background);for(int view:new int[]{R.id.title,R.id.widget_status,R.id.widget_empty,R.id.widget_refresh})v.setTextColor(view,view==R.id.title?AttentionCards.ink(c):AttentionCards.muted(c));
  v.setTextViewText(R.id.widget_empty,CalendarStore.prefs(c).getLong("lastSync",0)==0?"点击右上角刷新\n或打开 APP 检查连接":"目前没有待办\n点击标题查看日程");
  Intent home=new Intent(c,MainActivity.class).putExtra("page","agenda").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);PendingIntent open=PendingIntent.getActivity(c,id,home,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
  v.setOnClickPendingIntent(R.id.title,open);v.setOnClickPendingIntent(R.id.widget_status,open);
  v.setOnClickPendingIntent(R.id.widget_refresh,PendingIntent.getBroadcast(c,id,new Intent(c,CalendarWidget.class).setAction(REFRESH),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE));
 }
 static void bindTodoList(Context c,RemoteViews deck,int id){
  Intent detail=new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP).setData(Uri.parse("canvas-widget://detail/"+id));
  int flags=PendingIntent.FLAG_UPDATE_CURRENT;if(Build.VERSION.SDK_INT>=31)flags|=PendingIntent.FLAG_MUTABLE;
  deck.setPendingIntentTemplate(R.id.widget_list,PendingIntent.getActivity(c,id,detail,flags));
  deck.setEmptyView(R.id.widget_list,R.id.widget_empty);
  // Bind on the app-widget root after its cards have been inserted. This keeps
  // collection metadata on the host's RemoteViews, including after parceling.
  if(Build.VERSION.SDK_INT>=31){
   WidgetListService.Rows rows=new WidgetListService.Rows(c);rows.onDataSetChanged();
   RemoteViews.RemoteCollectionItems.Builder items=new RemoteViews.RemoteCollectionItems.Builder().setHasStableIds(false).setViewTypeCount(1);
   for(int n=0;n<rows.getCount();n++)items.addItem(n,rows.getViewAt(n));
   deck.setRemoteAdapter(R.id.widget_list,items.build());
  }else{
   Intent service=new Intent(c,WidgetListService.class).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID,id);
   service.setData(Uri.parse("canvas-widget://todos/"+id+"/"+CalendarStore.prefs(c).getLong("lastSync",0)));
   deck.setRemoteAdapter(R.id.widget_list,service);
  }
 }

}
