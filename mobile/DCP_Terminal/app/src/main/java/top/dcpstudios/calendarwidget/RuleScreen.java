package top.dcpstudios.calendarwidget;

import android.graphics.Typeface;
import android.view.Gravity;
import android.widget.*;
import org.json.*;
import java.util.*;

final class RuleScreen {
 final MainActivity a;final JSONObject draft;LinearLayout body;TextView saved;int tab=0,mode=0;String group="group";
 RuleScreen(MainActivity a,JSONObject cfg)throws JSONException{this.a=a;draft=new JSONObject(cfg.toString());}
 void show(){a.base("rules");a.root.addView(a.button("‹ 设置",a::settings));a.screenTitle("消息规则","");Ui.Choice tabs=new Ui.Choice(a,new String[]{"分类","工作状态","日程助手"},tab,3);tabs.onChange(n->{tab=n;render();});a.root.addView(tabs);ScrollView scroll=new ScrollView(a);body=a.column();scroll.addView(body);a.root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));saved=a.text("未保存的修改仅在此页保留",11,a.muted);a.root.addView(saved);Button save=a.button("保存规则",()->TerminalSettings.run(a,()->{NetDiskSession.Reply reply=TerminalClient.requestBound(a,"/attention",new JSONObject().put("settings",draft),null);AttentionSettings.cache(a,reply);a.runOnUiThread(()->{try{NetDiskSession.guard(a,reply.account,()->{saved.setText("已保存到服务器");Ui.enter(saved,0);});}catch(Exception ignored){}});return null;}));a.root.addView(save);render();}
 void render(){body.removeAllViews();try{if(tab==0)categories();else if(tab==1)matrix();else schedule();Ui.enter(body,0);}catch(Exception e){a.error(e);}}
 void changed(){saved.setText("有未保存的修改");}
 void put(String key,Object value){try{draft.put(key,value);changed();}catch(Exception e){a.error(e);}}
 Ui.Choice choose(LinearLayout parent,String[] names,int selected,int columns){Ui.Choice c=new Ui.Choice(a,names,selected,columns);parent.addView(c);return c;}
 void categories()throws Exception{
  Ui.label(a,body,"分类默认处理");choose(body,new String[]{"群聊","联系人"},group.equals("group")?0:1,2).onChange(n->{group=n==0?"group":"contact";render();});
  JSONArray cats=draft.getJSONObject("categories").getJSONArray(group);for(int i=0;i<cats.length();i++){String cat=cats.getString(i);LinearLayout row=a.column();TextView name=a.text(cat,14,a.ink);name.setTypeface(null,Typeface.BOLD);name.setPadding(a.d(2),a.d(10),0,a.d(3));row.addView(name);String action="inherit";JSONArray rules=draft.getJSONArray("rules");for(int j=0;j<rules.length();j++){JSONObject r=rules.getJSONObject(j);if((group.equals(r.optString("kind"))||"all".equals(r.optString("kind")))&&cat.equals(r.optString("category"))){action=r.optString("action");break;}}
   choose(row,new String[]{"跟随","提醒","静默","忽略"},AttentionSettings.index(AttentionSettings.ACTIONS,action),4).onChange(n->updateRule(cat,AttentionSettings.ACTIONS[n]));body.addView(row);
  }Ui.divider(a,body);Ui.label(a,body,"微信已免打扰的群");choose(body,new String[]{"跟随","提醒","静默","忽略"},AttentionSettings.index(AttentionSettings.ACTIONS,draft.optString("muted_action")),4).onChange(n->put("muted_action",AttentionSettings.ACTIONS[n]));
  TextView priority=a.text("会话设置 › 分类规则 › 免打扰规则 › 工作状态",11,a.muted);priority.setPadding(0,a.d(10),0,a.d(8));body.addView(priority);body.addView(a.text("忽略：不进入消息列表或日程助手。静默：保留未读，不提醒。",12,a.muted));
 }
 void updateRule(String cat,String action){try{JSONArray out=new JSONArray();out.put(new JSONObject().put("kind",group).put("category",cat).put("action",action));JSONArray old=draft.getJSONArray("rules");for(int i=0;i<old.length();i++){JSONObject r=old.getJSONObject(i);if(!(group.equals(r.optString("kind"))&&cat.equals(r.optString("category"))))out.put(r);}put("rules",out);}catch(Exception e){a.error(e);}}
 void matrix()throws Exception{
  Ui.label(a,body,"当前编辑的工作状态");choose(body,new String[]{"正常","工作","免打扰","学习"},mode,4).onChange(n->{mode=n;render();});
  String key=AttentionSettings.MODES[mode];JSONObject table=draft.getJSONObject("matrix").getJSONObject(key);String[] values={"notify","quiet","reply"};
  for(String kind:AttentionSettings.KINDS){LinearLayout row=new LinearLayout(a);row.setGravity(Gravity.CENTER_VERTICAL);TextView name=a.text(kind,13,a.ink);row.addView(name,new LinearLayout.LayoutParams(a.d(76),-2));Ui.Choice options=new Ui.Choice(a,new String[]{"提醒","静默","预留回复"},AttentionSettings.index(values,table.getString(kind)),3);options.onChange(n->{try{table.put(kind,values[n]);changed();}catch(Exception e){a.error(e);}});row.addView(options,new LinearLayout.LayoutParams(0,-2,1));body.addView(row);}
  body.addView(a.text("预留回复目前仅静默收纳，不发送微信。",11,a.muted));Ui.divider(a,body);Ui.label(a,body,"重要消息关键词");EditText words=AttentionSettings.multiline(a,body,"每行一个关键词",String.join("\n",AttentionSettings.strings(draft.getJSONArray("important_words"))));watch(words,()->put("important_words",AttentionSettings.lines(words.getText().toString())));
 }
 void schedule()throws Exception{
  Ui.label(a,body,"允许识别日程的分类");JSONArray allowed=draft.getJSONArray("schedule_categories");Set<String> selected=new LinkedHashSet<>();for(int i=0;i<allowed.length();i++)selected.add(allowed.getString(i));
  Switch all=new Switch(a);all.setText("全部分类");all.setTextSize(13);all.setTextColor(a.ink);all.setChecked(draft.isNull("schedule_all")?selected.isEmpty():draft.optBoolean("schedule_all"));all.setPadding(0,a.d(8),0,a.d(8));body.addView(all);LinearLayout choices=a.column();body.addView(choices);Set<String> unique=new LinkedHashSet<>();for(String group:new String[]{"group","contact"})Collections.addAll(unique,AttentionSettings.strings(draft.getJSONObject("categories").getJSONArray(group)));
  List<CheckBox> checks=new ArrayList<>();for(String cat:unique){CheckBox box=new CheckBox(a);box.setText(cat);box.setTextSize(13);box.setTextColor(a.ink);box.setMinHeight(a.d(40));box.setChecked(selected.contains(cat));box.setEnabled(!all.isChecked());box.setOnCheckedChangeListener((v,on)->{if(on)selected.add(cat);else selected.remove(cat);put("schedule_categories",new JSONArray(selected));});checks.add(box);choices.addView(box);}
  all.setOnCheckedChangeListener((v,on)->{put("schedule_all",on);if(on){selected.clear();for(CheckBox box:checks)box.setChecked(false);put("schedule_categories",new JSONArray());}else{selected.addAll(unique);for(CheckBox box:checks)box.setChecked(true);put("schedule_categories",new JSONArray(selected));}for(CheckBox box:checks)box.setEnabled(!on);});
  Ui.divider(a,body);Switch muted=new Switch(a);muted.setText("允许免打扰群进入日程助手");muted.setTextColor(a.ink);muted.setTextSize(13);muted.setChecked(draft.optBoolean("schedule_muted"));muted.setOnCheckedChangeListener((v,on)->put("schedule_muted",on));body.addView(muted);a.space(body,12);body.addView(a.button("编辑日程提示词与模型",()->new android.app.AlertDialog.Builder(a).setTitle("离开规则编辑？").setMessage("请先保存需要保留的规则。").setNegativeButton("继续编辑",null).setPositiveButton("打开",(d,n)->TerminalSettings.llm(a)).show()));
 }
 static void watch(EditText e,Runnable action){e.addTextChangedListener(new android.text.TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int after){}public void onTextChanged(CharSequence s,int st,int before,int count){action.run();}public void afterTextChanged(android.text.Editable s){}});}
}
