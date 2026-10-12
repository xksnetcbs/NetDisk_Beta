package top.dcpstudios.calendarwidget;

import android.app.*;import android.content.*;import android.text.InputType;import android.view.*;import android.widget.*;import org.json.*;import java.text.*;import java.util.*;

final class TerminalSettings {
    static void attach(MainActivity a,LinearLayout options){
        a.space(options,22);options.addView(a.text("消息与日程助手",14,a.muted));a.space(options,8);
        boolean enabled=TerminalClient.prefs(a).getBoolean("notifications",false);
        options.addView(a.button(enabled?"实时消息通知 · 已开启":"开启实时消息通知",()->{if(enabled){TerminalService.enable(a,false);a.settings();}else a.enableNotifications();}));
        toggle(a,options,"微信消息通知","notify_wechat");toggle(a,options,"Canvas 新作业通知","notify_canvas");
        options.addView(a.button("发送一条通知测试",()->run(a,()->{TerminalClient.request(a,"/test-notification",new JSONObject());return "测试已发送，请查看通知栏";})));
        options.addView(a.button("消息服务状态",()->run(a,()->{JSONObject h=TerminalClient.request(a,"/health",null);a.runOnUiThread(()->new AlertDialog.Builder(a).setTitle("消息服务").setMessage("版本 "+h.optString("version")+"\n已保存 "+h.optInt("count")+" 条消息\n微信采集："+(h.optJSONObject("wechat").optBoolean("ok")?"正常":"异常")+"\nCanvas 采集："+(h.optJSONObject("canvas").optBoolean("ok")?"正常":"异常")+"\n日程助手："+(h.optBoolean("llm_enabled")?"已启用":"未启用")).setPositiveButton("关闭",null).show());return null;})));
        options.addView(a.button("LLM 日程助手配置",()->llm(a)));
        options.addView(a.text("启用模型后，新微信文本会发送到你配置的接口。明确的安排自动加入日程，信息不足的消息保留在终端中供你查看。",13,a.muted));
    }
    static void toggle(MainActivity a,LinearLayout options,String title,String key){Switch s=new Switch(a);s.setText(title);s.setTextColor(a.ink);s.setTextSize(15);s.setPadding(a.d(12),a.d(12),a.d(12),a.d(12));s.setChecked(TerminalClient.prefs(a).getBoolean(key,true));s.setOnCheckedChangeListener((b,value)->TerminalClient.prefs(a).edit().putBoolean(key,value).apply());options.addView(s);}
    interface Operation {String run()throws Exception;}
    static void run(MainActivity a,Operation operation){TerminalClient.IO.execute(()->{try{String success=operation.run();if(success!=null)a.runOnUiThread(()->Toast.makeText(a,success,Toast.LENGTH_LONG).show());}catch(Exception e){a.runOnUiThread(()->a.error(e));}});}
    static EditText input(MainActivity a,LinearLayout form,String label,String value,boolean secret){form.addView(a.text(label,12,a.muted));EditText e=new EditText(a);e.setTextColor(a.ink);e.setTextSize(13);e.setSingleLine(true);e.setText(value);e.setPadding(a.d(8),a.d(6),a.d(8),a.d(6));if(secret)e.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);form.addView(e,new LinearLayout.LayoutParams(-1,a.d(42)));return e;}
    static void llm(MainActivity a){run(a,()->{NetDiskSession.Reply config=TerminalClient.requestBound(a,"/llm",null,null);NetDiskSession.ui(a,config.account,()->llmEditor(a,config.data));return null;});}
    static void llmEditor(MainActivity a,JSONObject config){
        LinearLayout form=a.column();form.setPadding(a.d(20),a.d(12),a.d(20),a.d(12));Switch enabled=new Switch(a);enabled.setText("自动识别并安排日程");enabled.setTextColor(a.ink);enabled.setChecked(config.optBoolean("enabled"));form.addView(enabled);
        EditText url=input(a,form,"OpenAI 兼容接口 · 如 https://服务商/v1",config.optString("base_url"),false);EditText model=input(a,form,"模型名称",config.optString("model"),false);EditText key=input(a,form,config.optBoolean("has_api_key")?"API Key · 留空保留已保存密钥":"API Key", "",true);EditText confidence=input(a,form,"自动安排最低置信度 · 0.5—1",String.valueOf(config.optDouble("threshold",.85)),false);
        EditText prompt=AttentionSettings.multiline(a,form,"日程分配提示词",config.optString("prompt"));EditText rules=AttentionSettings.multiline(a,form,"日程分配规则（例如：只安排明确提到我的任务）",config.optString("rules"));EditText duration=input(a,form,"未指定结束时间的默认时长（分钟）",String.valueOf(config.optInt("default_duration",60)),false);
        form.addView(a.text("默认不启用。启用后仅处理新微信文本；历史导入不会交给模型。分类范围可在消息披露与日程规则中设置。",13,a.muted));ScrollView scroll=new ScrollView(a);scroll.addView(form);
        AlertDialog dialog=new AlertDialog.Builder(a).setTitle("LLM 日程助手").setView(scroll).setNegativeButton("取消",null).setNeutralButton("测试已保存接口",null).setPositiveButton("保存配置",null).create();
        dialog.setOnShowListener(v->{dialog.getButton(-3).setOnClickListener(x->run(a,()->{TerminalClient.request(a,"/llm/test",new JSONObject());return "模型连接与 JSON 返回正常";}));dialog.getButton(-1).setOnClickListener(x->{try{
            JSONObject body=new JSONObject().put("enabled",enabled.isChecked()).put("base_url",url.getText().toString().trim()).put("model",model.getText().toString().trim()).put("threshold",Double.parseDouble(confidence.getText().toString())).put("prompt",prompt.getText().toString()).put("rules",rules.getText().toString()).put("default_duration",Integer.parseInt(duration.getText().toString()));if(key.length()>0)body.put("api_key",key.getText().toString());dialog.getButton(-1).setEnabled(false);
            TerminalClient.IO.execute(()->{try{NetDiskSession.Reply saved=TerminalClient.requestBound(a,"/llm",body,null);NetDiskSession.guard(a,saved.account,()->TerminalClient.prefs(a).edit().putString("llm",saved.data.toString()).apply());NetDiskSession.ui(a,saved.account,()->{dialog.dismiss();Toast.makeText(a,"日程助手配置已保存",Toast.LENGTH_SHORT).show();});}catch(NetDiskSession.AccountChanged ignored){}catch(Exception e){a.runOnUiThread(()->{dialog.getButton(-1).setEnabled(true);a.error(e);});}});
        }catch(Exception e){a.error(e);}});});dialog.show();
    }
    static void editSchedule(MainActivity a,String id){JSONObject schedule=null;for(JSONObject s:TerminalDb.get(a).schedules())if(id.equals(s.optString("id")))schedule=s;if(schedule==null){Toast.makeText(a,"请先同步日程",Toast.LENGTH_SHORT).show();return;}
        JSONObject current=schedule;SimpleDateFormat format=new SimpleDateFormat("yyyy-MM-dd HH:mm",Locale.CHINA);format.setLenient(false);
        LinearLayout form=a.column();form.setPadding(a.d(20),a.d(12),a.d(20),a.d(12));EditText title=input(a,form,"日程名称",current.optString("title"),false);EditText start=input(a,form,"开始 · yyyy-MM-dd HH:mm",format.format(new Date(current.optLong("start_at"))),false);EditText end=input(a,form,"结束 · yyyy-MM-dd HH:mm",format.format(new Date(current.optLong("end_at"))),false);EditText location=input(a,form,"地点",current.optString("location"),false);
        AlertDialog dialog=new AlertDialog.Builder(a).setTitle("编辑识别日程").setView(form).setNegativeButton("关闭",null).setNeutralButton("取消此日程",null).setPositiveButton("保存",null).create();dialog.setOnShowListener(v->{dialog.getButton(-3).setOnClickListener(x->run(a,()->{TerminalClient.request(a,"/schedules/"+id,new JSONObject().put("status","cancelled"));TerminalClient.sync(a,false);a.runOnUiThread(()->{dialog.dismiss();a.events=CalendarStore.read(a);a.home();});return "日程已取消";}));dialog.getButton(-1).setOnClickListener(x->{try{
            JSONObject body=new JSONObject().put("title",title.getText().toString().trim()).put("start_at",format.parse(start.getText().toString()).getTime()).put("end_at",format.parse(end.getText().toString()).getTime()).put("location",location.getText().toString());run(a,()->{TerminalClient.request(a,"/schedules/"+id,body);TerminalClient.sync(a,false);a.runOnUiThread(()->{dialog.dismiss();a.events=CalendarStore.read(a);a.home();});return "日程已更新";});
        }catch(Exception e){a.error(e);}});});dialog.show();
    }
}
