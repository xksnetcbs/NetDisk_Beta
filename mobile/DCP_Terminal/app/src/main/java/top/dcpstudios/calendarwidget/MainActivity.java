package top.dcpstudios.calendarwidget;

import android.app.*;import android.appwidget.*;import android.os.*;import android.content.*;import android.content.res.Configuration;import android.graphics.*;import android.graphics.drawable.*;import android.net.Uri;import android.text.InputType;import android.view.*;import android.webkit.*;import android.widget.*;import java.util.*;

public class MainActivity extends Activity {
 int background,surface,ink,muted,accent,line;boolean dark,archive=false,busy=false;String page="home";
 MessageScreen messageScreen;TimetableScreen timetableScreen;FocusHome focusHome;NetDiskScreen netDiskScreen;
 LinearLayout root,list;TextView status;List<CalendarData.Event> events=new ArrayList<>();
 final SharedPreferences.OnSharedPreferenceChangeListener accountChange=(p,k)->{if("user_id".equals(k)||"terminal_access".equals(k)||"session_cookie_digest".equals(k)||"signed_out".equals(k))runOnUiThread(()->{messageScreen=null;timetableScreen=null;events=CalendarStore.read(this);if(root!=null&&!"netdisk".equals(page))netdisk();});};
 final SharedPreferences.OnSharedPreferenceChangeListener terminalChange=(p,k)->{if("revision".equals(k))runOnUiThread(()->{if("messages".equals(page)&&messageScreen!=null)messageScreen.render();else if("home".equals(page)){events=CalendarStore.read(this);renderList();}});};
 final SharedPreferences.OnSharedPreferenceChangeListener change=(p,k)->{if("lastSync".equals(k)||"error".equals(k))runOnUiThread(()->{events=CalendarStore.read(this);if("home".equals(page))renderList();});if("timetable_sync_status".equals(k))runOnUiThread(()->{if("timetable".equals(page)&&timetableScreen!=null)timetableScreen.show();});};
 int d(float n){return (int)(n*getResources().getDisplayMetrics().density+.5f);}
 GradientDrawable bg(int c,int r){GradientDrawable g=new GradientDrawable();g.setColor(c);g.setCornerRadius(d(r));return g;}
 TextView text(String value,int size,int color){TextView t=new TextView(this);t.setText(value);t.setTextSize(size>=26?size-6:size>=16?size-2:size);t.setTextColor(color);t.setLineSpacing(d(2),1);t.setLetterSpacing(0);return t;}
 LinearLayout column(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.VERTICAL);return l;}
 void space(LinearLayout l,int h){l.addView(new View(this),new LinearLayout.LayoutParams(1,d(h)));}
 void touch(View v,int color){v.setBackground(new RippleDrawable(android.content.res.ColorStateList.valueOf(dark?0x22ffffff:0x16000000),bg(color,8),null));}
 Button button(String label,Runnable run){Button b=new Button(this);b.setText(label);b.setTextSize(12);b.setAllCaps(false);b.setTextColor(accent);b.setMinHeight(d(40));b.setMinimumHeight(d(40));b.setMinWidth(0);b.setMinimumWidth(0);b.setElevation(0);b.setStateListAnimator(null);b.setPadding(d(10),d(6),d(10),d(6));touch(b,label.startsWith("‹")?background:surface);if(label.startsWith("‹"))b.setGravity(Gravity.CENTER_VERTICAL|Gravity.START);LinearLayout.LayoutParams bp=new LinearLayout.LayoutParams(-1,-2);bp.topMargin=d(3);bp.bottomMargin=d(5);b.setLayoutParams(bp);b.setOnClickListener(v->run.run());Ui.press(b);return b;}
 @Override public void onCreate(Bundle state){
  String theme=CalendarStore.prefs(this).getString("theme","system");dark="dark".equals(theme)||("system".equals(theme)&&(getResources().getConfiguration().uiMode&Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES);
  setTheme(dark?R.style.AppThemeDark:R.style.AppTheme);super.onCreate(state);
  background=Color.parseColor(dark?"#000000":"#F2F2F7");surface=Color.parseColor(dark?"#1C1C1E":"#FFFFFF");ink=Color.parseColor(dark?"#F2F2F7":"#1C1C1E");muted=Color.parseColor(dark?"#98989D":"#6C6C70");accent=Color.parseColor(dark?"#64A8FF":"#007AFF");line=Color.parseColor(dark?"#38383A":"#E5E5EA");
  getWindow().setStatusBarColor(background);getWindow().setNavigationBarColor(background);getWindow().getDecorView().setSystemUiVisibility(dark?0:View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
  events=CalendarStore.read(this);CalendarStore.prefs(this).registerOnSharedPreferenceChangeListener(change);SyncJobService.schedule(this,true);
  archive=state!=null&&state.getBoolean("archive",false);
  TerminalClient.prefs(this).registerOnSharedPreferenceChangeListener(terminalChange);
  NetDiskSession.prefs(this).registerOnSharedPreferenceChangeListener(accountChange);
  if(!openFromIntent()){if("messages".equals(getIntent().getStringExtra("page")))messages();else if("agenda".equals(getIntent().getStringExtra("page")))agenda();else if("netdisk".equals(getIntent().getStringExtra("page")))netdisk();else if(!NetDiskSession.isLoggedIn(this))netdisk();else home();refresh();}
  AttentionCards.opened(this);
  TerminalClient.refresh(this,()->{});
  if(TerminalClient.prefs(this).getBoolean("notifications",false))TerminalService.enable(this,true);
  else if(NetDiskSession.isLoggedIn(this)&&!TerminalClient.prefs(this).getBoolean("notification_setup_seen",false)){TerminalClient.prefs(this).edit().putBoolean("notification_setup_seen",true).apply();root.post(this::enableNotifications);}

 }
 boolean openFromIntent(){long messageId=getIntent().getLongExtra("messageId",0);if(messageId>0){org.json.JSONObject message=TerminalDb.get(this).message(messageId);if(message!=null){messageScreen=new MessageScreen(this);messageScreen.detail(message);return true;}}String uid=getIntent().getStringExtra("uid");if(uid!=null)for(CalendarData.Event e:events)if(uid.equals(e.uid)){detail(e);return true;}
  String legacy=getIntent().getStringExtra("detail");if(legacy!=null){CalendarData.Event e=new CalendarData.Event();e.title=legacy;e.description=getIntent().getStringExtra("description");detail(e);return true;}return false;}
 @Override protected void onSaveInstanceState(Bundle b){b.putBoolean("archive",archive);super.onSaveInstanceState(b);}
 @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);AttentionCards.opened(this);if(!openFromIntent()){if("messages".equals(intent.getStringExtra("page")))messages();else if("agenda".equals(intent.getStringExtra("page")))agenda();else if("netdisk".equals(intent.getStringExtra("page")))netdisk();else home();}}
 @Override protected void onDestroy(){NetDiskPreview.closeAll(this);if(netDiskScreen!=null)netDiskScreen.destroy();CalendarStore.prefs(this).unregisterOnSharedPreferenceChangeListener(change);TerminalClient.prefs(this).unregisterOnSharedPreferenceChangeListener(terminalChange);NetDiskSession.prefs(this).unregisterOnSharedPreferenceChangeListener(accountChange);super.onDestroy();}
 @Override protected void onStart(){super.onStart();AttentionCards.opened(this);}
 @Override protected void onStop(){if(focusHome!=null)focusHome.stop();super.onStop();}
 @Override protected void onResume(){super.onResume();if(root!=null&&"home".equals(page)){events=CalendarStore.read(this);renderList();}if(focusHome!=null&&"focus".equals(page)){focusHome.stop();focusHome.tick.run();}}
 @Override public void onBackPressed(){if("netdisk".equals(page)&&netDiskScreen!=null&&netDiskScreen.back())return;if(!"focus".equals(page)){archive=false;home();}else super.onBackPressed();}
 void base(String section){String previous=root==null?section:page;if(focusHome!=null)focusHome.stop();if(netDiskScreen!=null)netDiskScreen.stop();page=section;root=column();root.setPadding(d(16),d(8),d(16),d(8));root.setBackgroundColor(background);setContentView(root);
  root.setOnApplyWindowInsetsListener((v,i)->{v.setPadding(d(16)+i.getSystemWindowInsetLeft(),d(8)+i.getSystemWindowInsetTop(),d(16)+i.getSystemWindowInsetRight(),d(8)+i.getSystemWindowInsetBottom());return i;});root.requestApplyInsets();Ui.page(root,previous,section);}
 void home(){if(focusHome!=null)focusHome.stop();focusHome=new FocusHome(this);focusHome.show();}
 void agenda(){
  base("home");TextView eyebrow=text("DCP TERMINAL",11,muted);eyebrow.setLetterSpacing(.12f);root.addView(eyebrow);space(root,8);
  LinearLayout header=new LinearLayout(this);header.setGravity(Gravity.CENTER_VERTICAL);TextView title=text("日程",34,ink);title.setTypeface(null,Typeface.BOLD);header.addView(title,new LinearLayout.LayoutParams(0,-2,1));header.addView(button("新增",()->ScheduleEditor.show(this,null)),new LinearLayout.LayoutParams(d(64),d(48)));header.addView(button("设置",this::settings),new LinearLayout.LayoutParams(d(80),d(48)));root.addView(header);
  status=text("",12,muted);status.setPadding(0,d(6),0,d(10));status.setOnClickListener(v->refresh());root.addView(status);
  LinearLayout tabs=new LinearLayout(this);tabs.addView(button(archive?"待办":"● 待办",()->{archive=false;agenda();}),new LinearLayout.LayoutParams(0,d(48),1));tabs.addView(button(archive?"● 归档":"归档",()->{archive=true;agenda();}),new LinearLayout.LayoutParams(0,d(48),1));tabs.addView(button("刷新",this::refresh),new LinearLayout.LayoutParams(0,d(48),1));root.addView(tabs);space(root,8);
  list=column();ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setClipToPadding(false);scroll.addView(list);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));navigation("home");renderList();
 }
 void renderList(){if(list==null||!"home".equals(page))return;list.removeAllViews();long now=System.currentTimeMillis();
  status.setText(busy?"正在同步日程…":CalendarStore.status(this));String error=CalendarStore.prefs(this).getString("error","");
  if(!error.isEmpty()){TextView err=text(error+"\n已保留上次成功数据，点击重试。",13,dark?0xFFFFB6A1:0xFF9C4630);err.setPadding(d(14),d(12),d(14),d(12));touch(err,surface);err.setOnClickListener(v->refresh());list.addView(err);space(list,12);}
  List<CalendarData.Event> shown=CalendarData.visible(events,now,CalendarStore.prefs(this).getBoolean("showDone",true),archive);
  if(shown.isEmpty()){list.addView(text(archive?"这里还没有归档日程":events.isEmpty()?"同步成功后，作业会显示在这里。":"当前没有需要显示的日程。",15,muted));return;}
  boolean headingDone=false,headingPending=false;
  for(CalendarData.Event e:shown){if(!archive&&((e.completed&&!headingDone)||(!e.completed&&!headingPending))){TextView section=text(e.completed?"近期完成":"待完成",14,muted);section.setPadding(d(2),d(4),0,d(12));list.addView(section);if(e.completed)headingDone=true;else headingPending=true;}card(e);}
 }
 void card(CalendarData.Event e){long now=System.currentTimeMillis();boolean late=!e.completed&&e.due>0&&e.due<now;boolean urgent=!e.completed&&e.due>now&&e.due-now<=4*3600000L;int tone=e.completed?muted:(late||urgent)?(dark?0xFFFF6B62:0xFFC62828):accent;
  LinearLayout card=column();card.setPadding(d(12),d(10),d(12),d(10));VisualStyles.apply(this,card,VisualStyles.event(this,e));if(!e.course.isEmpty())card.setBackground(bg(VisualStyles.blend(surface,VisualStyles.courseColor(this,e.course,e.course.hashCode()),dark?.16f:.08f),12));Ui.press(card);
  TextView meta=text((e.course.isEmpty()?"Canvas 作业":e.course)+"  ·  "+CalendarData.timing(e,now),12,tone);card.addView(meta);space(card,8);
  TextView title=text((e.completed?"✓  ":"")+e.title,18,ink);title.setTypeface(null,Typeface.BOLD);if(urgent||late)title.setTextColor(tone);card.addView(title);space(card,10);card.addView(text("截止  "+CalendarData.format(e.due)+"   ›",13,urgent?tone:muted));
  card.setOnLongClickListener(v->{VisualStyles.assign(this,e);return true;});card.setOnClickListener(v->detail(e));card.setContentDescription(e.title+"，"+CalendarData.timing(e,now)+"，"+CalendarData.format(e.due));card.setFocusable(true);
  LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.bottomMargin=d(12);list.addView(card,lp);
 }
 void refresh(){if(busy)return;busy=true;renderList();SyncJobService.EXECUTOR.execute(()->{try{CalendarStore.sync(this);}catch(Exception ignored){}CalendarWidget.renderAll(this);runOnUiThread(()->{busy=false;events=CalendarStore.read(this);if(!isDestroyed())renderList();});});}
 void detail(CalendarData.Event e){
  base("detail");root.addView(button("‹ 返回日程",this::agenda));TextView title=text(e.title,26,ink);title.setTypeface(null,Typeface.BOLD);root.addView(title);space(root,12);
  TextView meta=text((e.course.isEmpty()?"Canvas 作业":e.course)+"\n"+CalendarData.timing(e,System.currentTimeMillis())+"  ·  截止 "+CalendarData.format(e.due),14,muted);meta.setPadding(d(16),d(12),d(16),d(12));meta.setBackground(bg(surface,18));root.addView(meta);space(root,12);
  WebView web=new WebView(this);web.setBackgroundColor(surface);web.getSettings().setJavaScriptEnabled(false);web.getSettings().setAllowFileAccess(false);web.getSettings().setAllowContentAccess(false);web.getSettings().setDefaultTextEncodingName("UTF-8");
  web.setWebViewClient(new WebViewClient(){@Override public boolean shouldOverrideUrlLoading(WebView w,WebResourceRequest request){external(request.getUrl().toString());return true;}});
  String body=e.description==null||e.description.isEmpty()?"<p>暂无详细说明</p>":e.description;
  String css="body{padding:8px;font:16px/1.8 sans-serif;color:"+(dark?"#E0ECE6":"#263E34")+";overflow-wrap:anywhere}img,video,iframe{max-width:100%;height:auto}a{color:"+(dark?"#64A8FF":"#007AFF")+"}table{max-width:100%;display:block;overflow:auto}";
  web.loadDataWithBaseURL("https://canvas.tongji.edu.cn/","<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><style>"+css+"</style></head><body>"+body+"</body></html>","text/html","UTF-8",null);root.addView(web,new LinearLayout.LayoutParams(-1,0,1));
  if(!e.url.isEmpty())root.addView(button(e.uid.startsWith("netdisk:")?"在网盘中打开":"在 Canvas 中打开",()->{if(e.uid.startsWith("netdisk:"))netdisk();else external(e.url);}));
  root.addView(button("管理作业状态",()->manageTask(e)));org.json.JSONObject schedule=ScheduleEditor.find(this,e.uid);if(schedule!=null&&schedule.optBoolean("editable"))root.addView(button("编辑日程",()->ScheduleEditor.show(this,schedule)));
  if(schedule!=null&&schedule.optBoolean("deletable"))root.addView(button("删除日程",()->new AlertDialog.Builder(this).setTitle("删除此日程？").setMessage("将同步删除服务器上的此日程。").setNegativeButton("取消",null).setPositiveButton("删除",(a,b)->SyncJobService.EXECUTOR.execute(()->{try{CalendarStore.delete(this,e.uid);CalendarWidget.renderAll(this);runOnUiThread(()->{events=CalendarStore.read(this);home();});}catch(Exception ex){runOnUiThread(()->Toast.makeText(this,ex.getMessage(),Toast.LENGTH_LONG).show());}})).show()));
 }
 void external(String url){try{Uri u=Uri.parse(url);if("https".equals(u.getScheme())||"http".equals(u.getScheme()))startActivity(new Intent(Intent.ACTION_VIEW,u));}catch(Exception ex){Toast.makeText(this,"没有可用的浏览器",Toast.LENGTH_SHORT).show();}}
 void settings(){
  base("settings");root.addView(button("‹ 返回首页",this::home));TextView title=text("设置",30,ink);title.setTypeface(null,Typeface.BOLD);root.addView(title);space(root,16);ScrollView scroll=new ScrollView(this);LinearLayout options=column();scroll.addView(options);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
  options.addView(text("显示与排序",14,muted));space(options,10);
  toggle(options,"显示近期已完成作业","showDone",true);
  TextView rule=text("未完成优先。可手动归档逾期作业、强制完成；完成且截止超过 7 天会自动归档。",13,muted);rule.setPadding(d(4),d(10),d(4),d(18));options.addView(rule);
  options.addView(button("外观 · "+themeName(),()->Ui.select(this,"外观",new String[]{"跟随系统","浅色","深色"},AttentionSettings.index(new String[]{"system","light","dark"},CalendarStore.prefs(this).getString("theme","system")),b->{CalendarStore.prefs(this).edit().putString("theme",new String[]{"system","light","dark"}[b]).apply();CalendarWidget.renderAll(this);recreate();})));
  int interval=CalendarStore.prefs(this).getInt("interval",30);options.addView(button("后台同步 · "+(interval==0?"仅手动":interval+" 分钟"),()->Ui.select(this,"后台同步频率",new String[]{"15 分钟","30 分钟","60 分钟","仅手动"},java.util.Arrays.asList(15,30,60,0).indexOf(interval),b->{CalendarStore.prefs(this).edit().putInt("interval",new int[]{15,30,60,0}[b]).apply();SyncJobService.schedule(this,false);settings();})));
  options.addView(text("桌面卡片自动轮播；点击卡片打开应用。日程页可手动刷新，系统省电可能延后后台更新。",13,muted));space(options,20);
  options.addView(text("桌面与连接",14,muted));space(options,8);options.addView(button("添加桌面卡片",this::pinWidget));options.addView(button("网盘账号与站点",this::netdisk));
  options.addView(button("同步状态",()->new AlertDialog.Builder(this).setTitle(CalendarStore.status(this)).setMessage("缓存日程："+events.size()+"\n"+CalendarStore.prefs(this).getString("error","最近一次同步成功")+"\n\n手机同步服务器日历，Canvas 数据由服务器定时获取。").setPositiveButton("知道了",null).show()));
  if(NetDiskSession.canTerminal(this)){AttentionSettings.attach(this,options);TerminalSettings.attach(this,options);}else options.addView(text("网盘日程按当前账号同步；共享微信与日历仅向超级管理员开放。",13,muted));space(options,16);options.addView(text("DCP Terminal  1.6.3\n自动回复仅预留，不会自动发送微信消息。",11,muted));
 }
 String themeName(){String t=CalendarStore.prefs(this).getString("theme","system");return "dark".equals(t)?"深色":"light".equals(t)?"浅色":"跟随系统";}
 void toggle(LinearLayout box,String label,String key,boolean fallback){Switch s=new Switch(this);s.setText(label);s.setTextSize(13);s.setTextColor(ink);s.setPadding(d(8),d(8),d(8),d(8));s.setMinHeight(d(44));s.setChecked(CalendarStore.prefs(this).getBoolean(key,fallback));s.setOnCheckedChangeListener((b,checked)->{CalendarStore.prefs(this).edit().putBoolean(key,checked).apply();CalendarWidget.renderAll(this);});box.addView(s);}
 void pinWidget(){if(Build.VERSION.SDK_INT>=26){AppWidgetManager m=AppWidgetManager.getInstance(this);if(m.isRequestPinAppWidgetSupported()){m.requestPinAppWidget(new ComponentName(this,CalendarWidget.class),null,null);return;}}new AlertDialog.Builder(this).setMessage("请长按桌面空白处，选择“小组件”，找到“DCP Terminal”。").setPositiveButton("知道了",null).show();}

 void screenTitle(String title,String subtitle){TextView h=text(title,32,ink);h.setTypeface(null,Typeface.BOLD);root.addView(h);if(!subtitle.isEmpty()){TextView sub=text(subtitle,13,muted);sub.setPadding(0,d(6),0,d(16));root.addView(sub);}else space(root,16);}
 void navigation(String selected){LinearLayout bar=new LinearLayout(this);bar.setPadding(d(4),d(4),d(4),d(4));bar.setBackground(bg(dark?0xEB252527:0xEBFFFFFF,22));String[] names={"状态","日程","消息","课表","网盘"},ids={"focus","home","messages","timetable","netdisk"};for(int i=0;i<5;i++){final String id=ids[i];Button b=button(names[i],()->{if("focus".equals(id))home();else if("home".equals(id))agenda();else if("messages".equals(id))messages();else if("netdisk".equals(id))netdisk();else timetable();});b.setTextColor(selected.equals(id)?accent:muted);touch(b,selected.equals(id)?(dark?0xFF343438:0xFFEAF1FF):android.graphics.Color.TRANSPARENT);bar.addView(b,new LinearLayout.LayoutParams(0,d(48),1));}root.addView(bar,new LinearLayout.LayoutParams(-1,-2));}
 void netdisk(){if(netDiskScreen==null)netDiskScreen=new NetDiskScreen(this);netDiskScreen.show();}
 void messages(){if(messageScreen==null)messageScreen=new MessageScreen(this);messageScreen.show();}
 void timetable(){if(timetableScreen==null)timetableScreen=new TimetableScreen(this);timetableScreen.show();}
 void error(Exception e){Toast.makeText(this,e.getMessage()==null?"操作失败，请重试":e.getMessage(),Toast.LENGTH_LONG).show();}
 void enableNotifications(){if(android.os.Build.VERSION.SDK_INT>=33&&checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED)requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS},71);else{TerminalService.enable(this,true);Toast.makeText(this,"实时消息通知已开启",Toast.LENGTH_SHORT).show();}}
 @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results){super.onRequestPermissionsResult(request,permissions,results);if(request==71){boolean granted=results.length>0&&results[0]==android.content.pm.PackageManager.PERMISSION_GRANTED;if(granted)TerminalService.enable(this,true);else TerminalClient.prefs(this).edit().putBoolean("notifications",false).apply();if("settings".equals(page))settings();}}
 void manageTask(CalendarData.Event e){java.util.List<String> labels=new java.util.ArrayList<>();java.util.List<Runnable> actions=new java.util.ArrayList<>();
  if(e.manuallyArchived){labels.add("取消手动归档");actions.add(()->TaskOverrides.archive(this,e.uid,false));}else if(e.due>0&&e.due<System.currentTimeMillis()){labels.add("归档逾期作业");actions.add(()->TaskOverrides.archive(this,e.uid,true));}
  labels.add(e.forcedCompleted?"取消强制完成":"强制完成");actions.add(()->TaskOverrides.complete(this,e.uid,!e.forcedCompleted));
  Ui.select(this,"个人作业状态",labels.toArray(new String[0]),-1,index->{actions.get(index).run();events=CalendarStore.read(this);agenda();Toast.makeText(this,TaskOverrides.pending(this,e.uid)?"完成状态已保存，正在同步服务器":"个人状态已保存",Toast.LENGTH_SHORT).show();});
 }
 @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request==44&&netDiskScreen!=null){netDiskScreen.handleDownload(result,data);return;}if(request==43&&netDiskScreen!=null){netDiskScreen.handleUpload(result,data);return;}if(result!=RESULT_OK||data==null||data.getData()==null)return;android.net.Uri uri=data.getData();
  if(request==41)TerminalClient.IO.execute(()->{try{java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();try(java.io.InputStream in=getContentResolver().openInputStream(uri)){byte[] buffer=new byte[4096];int n;while((n=in.read(buffer))!=-1){bytes.write(buffer,0,n);if(bytes.size()>1024*1024)throw new java.io.IOException("JSON 文件不能超过 1 MB");}}String json=new String(bytes.toByteArray(),java.nio.charset.StandardCharsets.UTF_8);runOnUiThread(()->{if(timetableScreen==null)timetableScreen=new TimetableScreen(this);timetableScreen.importJson(json);});}catch(Exception e){runOnUiThread(()->error(e));}});
  if(request==42)TerminalClient.IO.execute(()->{try(java.io.OutputStream out=getContentResolver().openOutputStream(uri)){out.write(TimetableStore.load(this).toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));runOnUiThread(()->Toast.makeText(this,"课表已导出",Toast.LENGTH_SHORT).show());}catch(Exception e){runOnUiThread(()->error(e));}});
 }
}
