package top.dcpstudios.calendarwidget;
import android.app.*;
import android.widget.*;
import android.text.InputType;
import org.json.*;
import java.util.*;
import java.net.URLEncoder;

/** Native date/time pickers create the current account's server calendar event. */
final class ScheduleEditor {
    static JSONObject find(MainActivity activity,String uid){for(JSONObject s:TerminalDb.get(activity).schedules())if(uid.equals(s.optString("id")))return s;return null;}
    static void show(MainActivity a,JSONObject current){
        if(!NetDiskSession.isLoggedIn(a)){a.netdisk();return;}
        final NetDiskSession.Account account;try{account=NetDiskSession.account(a);}catch(Exception e){a.error(e);return;}
        String clientId="android-"+UUID.randomUUID();long now=System.currentTimeMillis();Calendar start=Calendar.getInstance(),end=Calendar.getInstance();start.setTimeInMillis(current==null?now:current.optLong("start_at",now));end.setTimeInMillis(current==null?now+3600000:current.optLong("end_at",now+3600000));
        LinearLayout box=a.column();box.setPadding(a.d(20),a.d(10),a.d(20),a.d(10));EditText title=input(a,box,"日程名称",current==null?"":current.optString("title"));
        Button from=a.button("",()->pick(a,start,()->{})),until=a.button("",()->pick(a,end,()->{}));
        Runnable labels=()->{from.setText("开始  "+CalendarData.format(start.getTimeInMillis()));until.setText("结束  "+CalendarData.format(end.getTimeInMillis()));};from.setOnClickListener(v->pick(a,start,labels));until.setOnClickListener(v->pick(a,end,labels));labels.run();box.addView(from);box.addView(until);
        EditText location=input(a,box,"地点（可选）",current==null?"":current.optString("location")),description=input(a,box,"说明（可选）",current==null?"":current.optString("description"));description.setSingleLine(false);description.setMinLines(3);
        ScrollView scroll=new ScrollView(a);scroll.addView(box);AlertDialog dialog=new AlertDialog.Builder(a).setTitle(current==null?"新增日程":"编辑日程").setView(scroll).setNegativeButton("取消",null).setPositiveButton("保存到服务器",null).create();
        dialog.setOnShowListener(d->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{if(title.getText().toString().trim().isEmpty()){title.setError("请输入日程名称");return;}if(end.getTimeInMillis()<=start.getTimeInMillis()){Toast.makeText(a,"结束时间应晚于开始时间",Toast.LENGTH_SHORT).show();return;}
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false);TerminalClient.IO.execute(()->{try{
                JSONObject body=new JSONObject().put("title",title.getText().toString().trim()).put("start_at",start.getTimeInMillis()).put("end_at",end.getTimeInMillis()).put("location",location.getText().toString()).put("description",description.getText().toString());
                if(current==null)body.put("id",clientId);String path="/api/mobile/terminal/schedules"+(current==null?"":"/"+URLEncoder.encode(current.getString("id"),"UTF-8"));
                NetDiskSession.requestMethod(a,path,"POST",body,account);TerminalClient.sync(a,false);
                NetDiskSession.ui(a,account,()->{dialog.dismiss();a.events=CalendarStore.read(a);a.agenda();Toast.makeText(a,"日程已保存到服务器",Toast.LENGTH_SHORT).show();});
            }catch(NetDiskSession.AccountChanged ignored){a.runOnUiThread(dialog::dismiss);}catch(Exception error){a.runOnUiThread(()->{dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(true);a.error(error);});}});
        }));dialog.show();
    }
    private static EditText input(MainActivity a,LinearLayout box,String hint,String value){EditText input=new EditText(a);input.setHint(hint);input.setText(value);input.setTextColor(a.ink);input.setHintTextColor(a.muted);input.setTextSize(16);input.setSingleLine(true);input.setInputType(InputType.TYPE_CLASS_TEXT);box.addView(input);a.space(box,10);return input;}
    private static void pick(MainActivity a,Calendar value,Runnable done){new DatePickerDialog(a,(view,year,month,day)->{
        new TimePickerDialog(a,(clock,hour,minute)->{value.set(year,month,day,hour,minute,0);value.set(Calendar.MILLISECOND,0);done.run();},value.get(Calendar.HOUR_OF_DAY),value.get(Calendar.MINUTE),true).show();
    },value.get(Calendar.YEAR),value.get(Calendar.MONTH),value.get(Calendar.DAY_OF_MONTH)).show();}
}
