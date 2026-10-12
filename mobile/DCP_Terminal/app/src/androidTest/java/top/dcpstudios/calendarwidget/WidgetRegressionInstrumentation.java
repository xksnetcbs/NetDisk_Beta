package top.dcpstudios.calendarwidget;
import android.app.*;import android.appwidget.*;import android.content.*;import android.os.*;import android.view.*;import android.widget.*;import java.nio.charset.StandardCharsets;import java.io.*;import java.util.Locale;
/** Real app-widget-host regression check; only used by the isolated test APK. */
public class WidgetRegressionInstrumentation extends Instrumentation {
 Activity activity;AppWidgetHost host;AppWidgetHostView widget;ListView list;int widgetId;Context context;
 public void onCreate(Bundle args){super.onCreate(args);start();}
 void progress(String message){Bundle update=new Bundle();update.putString("stream",message+"\n");sendStatus(1,update);}
 void check(boolean ok,String message){if(!ok)throw new AssertionError(message);progress("PASS "+message);}
 void seed(int count,boolean done)throws Exception{
  org.json.JSONArray rows=new org.json.JSONArray();long due=CalendarData.date("20261201T120000Z","");for(int n=0;n<count;n++)rows.put(new org.json.JSONObject().put("id","regression-"+String.format(Locale.US,"%02d",n)).put("title","测试待办 "+n).put("end_at",due).put("start_at",due-3600000).put("source","canvas").put("course","Canvas 作业").put("source_completed",done).put("forced_completed",false).put("completed",done).put("status",done?"completed":"active"));
  rows.put(new org.json.JSONObject().put("id","already-done").put("title","已完成，不应出现").put("source_completed",true).put("forced_completed",false).put("completed",true).put("status","completed"));TerminalDb.get(context).schedules(rows);
  TimetableCalendarRegression.raw(TerminalDb.get(context),new org.json.JSONObject().put("id","timetable:old-widget-course:1").put("source","timetable").put("title","课表不得进入日程组件").put("end_at",due).put("status","active"));
 }
 void awaitCount(int expected)throws Exception{
  for(int n=0;n<150;n++){final int[] count={-1};runOnMainSync(()->{list=widget.findViewById(R.id.widget_list);if(list!=null&&list.getAdapter()!=null)count[0]=list.getCount();});if(count[0]==expected)return;Thread.sleep(100);}
  throw new AssertionError("Expected "+expected+" rows, got "+(list==null?"no list":list.getCount()));
 }
 public void onStart(){Bundle result=new Bundle();int code=Activity.RESULT_OK;
  try{
   context=getTargetContext();NetDiskSession.prefs(context).edit().putString("origin","https://127.0.0.1:1").putBoolean("signed_out",false).putLong("user_id",1).putBoolean("terminal_access",true).commit();runOnMainSync(()->android.webkit.CookieManager.getInstance().setCookie("https://127.0.0.1:1/api/auth/refresh","dcp_netdisk_session=isolated-widget-cookie; Path=/api/auth; Secure; HttpOnly"));android.webkit.CookieManager.getInstance().flush();Thread.sleep(100);NetDiskSession.prefs(context).edit().putString("session_cookie_digest",NetDiskSession.digest(NetDiskSession.cookie(context))).commit();CalendarStore.prefs(context).edit().putInt("interval",0).putString("url","https://127.0.0.1:1/calendar/").putLong("lastSync",System.currentTimeMillis()).putBoolean("widgetDone",false).commit();TerminalClient.prefs(context).edit().putBoolean("notification_setup_seen",true).putBoolean("notifications",false).commit();seed(48,false);
   progress("Starting isolated test activity without notification permission prompt");activity=startActivitySync(new Intent(context,MainActivity.class).putExtra("page","messages").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
   progress("Creating real app-widget host");runOnMainSync(()->{
    AppWidgetManager manager=AppWidgetManager.getInstance(context);host=new AppWidgetHost(context,94711);widgetId=host.allocateAppWidgetId();Bundle options=new Bundle();options.putInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH,250);options.putInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT,110);options.putInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT,110);
    if(!manager.bindAppWidgetIdIfAllowed(widgetId,new ComponentName(context,CalendarWidget.class),options))throw new AssertionError("Widget bind permission missing");
    host.startListening();widget=host.createView(activity,widgetId,manager.getAppWidgetInfo(widgetId));FrameLayout root=new FrameLayout(activity);root.setBackgroundColor(0xffdddddd);int height=(int)(110*activity.getResources().getDisplayMetrics().density);root.addView(widget,new FrameLayout.LayoutParams(-1,height));activity.setContentView(root);CalendarWidget.render(context,manager,widgetId);
   });
   progress("Waiting for complete collection");awaitCount(48);check(list.getCount()==48,"all 48 pending rows present in 4x2 widget; completed excluded");
   progress("Checking scroll and item click");
   runOnMainSync(()->{ViewFlipper deck=widget.findViewById(R.id.card_flipper);deck.stopFlipping();deck.setDisplayedChild(0);});
   final int[] visible={-1,0,0};for(int n=0;n<200;n++){runOnMainSync(()->{visible[1]=list.getHeight();visible[2]=list.getChildCount();});if(visible[1]>0&&visible[2]>0)break;Thread.sleep(100);}
   check(visible[1]>0&&visible[2]>0,"todo card laid out and visible");
   runOnMainSync(()->list.setSelectionFromTop(47,0));for(int n=0;n<200;n++){runOnMainSync(()->visible[0]=list.getLastVisiblePosition());if(visible[0]==47)break;Thread.sleep(100);}
   check(visible[0]==47,"widget scroll reaches final pending item (last="+visible[0]+", height="+visible[1]+")");
   android.graphics.Bitmap screenshot=getUiAutomation().takeScreenshot();try(FileOutputStream out=new FileOutputStream(new File(context.getFilesDir(),"widget-last-item.png"))){screenshot.compress(android.graphics.Bitmap.CompressFormat.PNG,100,out);}


   progress("Checking refresh retains the list view");final ListView beforeRefresh=list;runOnMainSync(()->CalendarWidget.render(context,AppWidgetManager.getInstance(context),widgetId));Thread.sleep(500);runOnMainSync(()->list=widget.findViewById(R.id.widget_list));check(list==beforeRefresh,"refresh retains list view");check(list.getLastVisiblePosition()==47,"refresh retains final scroll position");
   seed(48,true);runOnMainSync(()->CalendarWidget.render(context,AppWidgetManager.getInstance(context),widgetId));awaitCount(0);check(list.getCount()==0,"completed items disappear after refresh");
   seed(48,false);runOnMainSync(()->CalendarWidget.render(context,AppWidgetManager.getInstance(context),widgetId));awaitCount(48);check(list.getCount()==48,"refresh restores all rows without stale empty cache");
   progress("Checking final row click");runOnMainSync(()->list.setSelectionFromTop(47,0));for(int n=0;n<200&&list.getLastVisiblePosition()!=47;n++)Thread.sleep(100);
   runOnMainSync(()->list.performItemClick(list.getChildAt(47-list.getFirstVisiblePosition()),47,list.getAdapter().getItemId(47)));for(int n=0;n<200&&!"regression-47".equals(activity.getIntent().getStringExtra("uid"));n++)Thread.sleep(100);check("regression-47".equals(activity.getIntent().getStringExtra("uid")),"row click opens the correct event detail");
   result.putString("stream","PASS: widget host, 48 rows, scrolling, correct row click, completion and refresh\n");
  }catch(Throwable error){code=Activity.RESULT_CANCELED;result.putString("stream","FAIL: "+error.toString()+"\n");error.printStackTrace();try{if(context!=null){android.graphics.Bitmap screen=getUiAutomation().takeScreenshot();try(FileOutputStream out=new FileOutputStream(new File(context.getFilesDir(),"widget-failure.png"))){screen.compress(android.graphics.Bitmap.CompressFormat.PNG,100,out);}if(list!=null)runOnMainSync(()->progress("List attached="+list.isAttachedToWindow()+", shown="+list.isShown()+", selected="+list.getSelectedItemPosition()+", first="+list.getFirstVisiblePosition()+", children="+list.getChildCount()+", density="+activity.getResources().getDisplayMetrics().density));}}catch(Exception ignored){}}
  finally{if(host!=null)runOnMainSync(()->{host.stopListening();host.deleteHost();});if(activity!=null)runOnMainSync(()->activity.finish());finish(code,result);}
 }
}
