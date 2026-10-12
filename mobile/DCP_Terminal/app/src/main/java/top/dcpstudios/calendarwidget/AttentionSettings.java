package top.dcpstudios.calendarwidget;
import android.app.*;import android.widget.*;import android.view.*;import org.json.*;import java.util.*;
final class AttentionSettings {
 static final String[] MODES={"正常","WORKING","免打扰","STUDY"};
 static final String[] KINDS={"工作消息","工作日程","科研任务","闲聊消息","工作询问","一般消息","重要"};
 static final String[] ACTIONS={"inherit","notify","quiet","ignore"},LABELS={"跟随规则","提醒","静默收纳","完全忽略"};
 static JSONObject state(android.content.Context c){if(!NetDiskSession.canTerminal(c))return new JSONObject();try{return new JSONObject(TerminalClient.prefs(c).getString("attention","{}"));}catch(Exception e){return new JSONObject();}}
 static void cache(android.content.Context c,NetDiskSession.Reply reply)throws Exception{NetDiskSession.guard(c,reply.account,()->TerminalClient.prefs(c).edit().putString("attention",reply.data.toString()).apply());}
 static void attach(MainActivity a,LinearLayout box){box.addView(a.button("分类颜色与卡片样式",()->VisualStyles.show(a)));box.addView(a.button("Canvas 科目颜色",()->VisualStyles.canvasColors(a)));box.addView(a.button("群聊分类与备注",()->directory(a,"group")));box.addView(a.button("联系人分类与备注",()->directory(a,"contact")));box.addView(a.button("消息披露与日程规则",()->rules(a)));}
 static Ui.Choice choice(MainActivity a,LinearLayout box,String title,String[] labels,int selected){box.addView(a.text(title,12,a.muted));Ui.Choice s=new Ui.Choice(a,labels,selected,labels.length<=4?labels.length:3);box.addView(s);return s;}
 static int index(String[] a,String value){return Arrays.asList(a).indexOf(value);}
 static String[] strings(JSONArray a){String[] r=new String[a.length()];for(int i=0;i<r.length;i++)r[i]=a.optString(i);return r;}
 static EditText multiline(MainActivity a,LinearLayout box,String title,String value){EditText e=TerminalSettings.input(a,box,title,value,false);e.setSingleLine(false);e.setMinLines(3);e.setGravity(Gravity.TOP);e.setLayoutParams(new LinearLayout.LayoutParams(-1,-2));return e;}
 static void directory(MainActivity a,String kind){new DirectoryScreen(a,kind).show();}
 static void categories(MainActivity a,String kind,JSONObject settings){try{LinearLayout form=a.column();EditText values=multiline(a,form,"每行一个分类",String.join("\n",strings(settings.getJSONObject("categories").getJSONArray(kind))));new AlertDialog.Builder(a).setTitle("编辑分类").setView(form).setNegativeButton("取消",null).setPositiveButton("保存",(d,w)->TerminalSettings.run(a,()->{JSONObject cats=new JSONObject(settings.getJSONObject("categories").toString());cats.put(kind,lines(values.getText().toString()));NetDiskSession.Reply result=TerminalClient.requestBound(a,"/attention",new JSONObject().put("settings",new JSONObject().put("categories",cats)),null);cache(a,result);a.runOnUiThread(()->directory(a,kind));return "分类已更新";})).show();}catch(Exception e){a.error(e);}}
 static JSONArray lines(String text){JSONArray a=new JSONArray();for(String s:text.split("[\n,，]"))if(!s.trim().isEmpty())a.put(s.trim());return a;}
 static void rules(MainActivity a){TerminalSettings.run(a,()->{NetDiskSession.Reply reply=TerminalClient.requestBound(a,"/attention",null,null);cache(a,reply);a.runOnUiThread(()->{try{NetDiskSession.guard(a,reply.account,()->new RuleScreen(a,reply.data.getJSONObject("settings")).show());}catch(Exception ignored){}});return null;});}
}
