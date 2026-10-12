package top.dcpstudios.calendarwidget;

import java.text.*;
import java.util.*;

/** Pure timetable arithmetic shared by the editor, week grid and tests. */
final class TimetableData {
    static final TimeZone ZONE=TimeZone.getTimeZone("Asia/Shanghai");
    static long monday(String text)throws IllegalArgumentException{
        SimpleDateFormat f=new SimpleDateFormat("yyyy-MM-dd",Locale.US);f.setTimeZone(ZONE);f.setLenient(false);
        ParsePosition p=new ParsePosition(0);Date date=f.parse(text,p);if(date==null||p.getIndex()!=text.length())throw new IllegalArgumentException("第一周周一应为 yyyy-MM-dd 格式");
        Calendar c=Calendar.getInstance(ZONE);c.setTime(date);if(c.get(Calendar.DAY_OF_WEEK)!=Calendar.MONDAY)throw new IllegalArgumentException("第一周起始日期必须是周一");return date.getTime();
    }
    static int minutes(String text){if(!text.matches("\\d{2}:\\d{2}"))throw new IllegalArgumentException("节次时间格式应为 HH:mm");int h=Integer.parseInt(text.substring(0,2)),m=Integer.parseInt(text.substring(3));if(h>23||m>59)throw new IllegalArgumentException("节次时间超出范围");return h*60+m;}
    static int week(long firstMonday,long now){return (int)Math.floor((now-firstMonday)/(7d*86400000))+1;}
    static SortedSet<Integer> numbers(String input,int min,int max){
        SortedSet<Integer> values=new TreeSet<>();String s=input.replace('，',',').replace("周","").replace("节","").replace(" ","").trim();
        boolean odd=s.endsWith("单"),even=s.endsWith("双");if(odd||even)s=s.substring(0,s.length()-1);
        if(s.isEmpty())throw new IllegalArgumentException("请填写范围，例如 1-16 或 1,3,5");
        for(String part:s.split(",",-1)){String[] range=part.split("-",-1);if(range.length>2)throw new IllegalArgumentException("范围格式不正确");
            try{int a=Integer.parseInt(range[0]),b=range.length==2?Integer.parseInt(range[1]):a;if(a<min||b>max||a>b)throw new IllegalArgumentException("范围应在 "+min+"—"+max+" 之间");for(int n=a;n<=b;n++)if((!odd&&!even)||(odd&&n%2==1)||(even&&n%2==0))values.add(n);}catch(NumberFormatException ex){throw new IllegalArgumentException("范围格式不正确");}
        }if(values.isEmpty())throw new IllegalArgumentException("范围中没有有效值");return values;
    }
    static String join(Collection<Integer> values){StringBuilder s=new StringBuilder();for(int n:values){if(s.length()>0)s.append(',');s.append(n);}return s.toString();}
}
