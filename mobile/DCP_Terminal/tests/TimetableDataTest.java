package top.dcpstudios.calendarwidget;
import java.util.*;
public class TimetableDataTest {
 static int passed;
 static void check(boolean condition,String name){if(!condition)throw new AssertionError(name);passed++;System.out.println("PASS "+name);}
 public static void main(String[] args){
  long first=TimetableData.monday("2026-09-07");
  check(TimetableData.week(first,first)==1,"first week begins on configured Monday");
  check(TimetableData.week(first,first-1)==0,"before semester");
  check(TimetableData.week(first,first+7*86400000L)==2,"week boundary");
  check(TimetableData.numbers("1-8单",1,20).equals(new TreeSet<>(Arrays.asList(1,3,5,7))),"odd weeks");
  check(TimetableData.numbers("2-10双",1,20).equals(new TreeSet<>(Arrays.asList(2,4,6,8,10))),"even weeks");
  check(TimetableData.numbers("1-2,5,11",1,11).size()==4,"non-contiguous lessons through 11");
  check(TimetableData.minutes("23:59")==1439,"time upper bound");
  for(String invalid:new String[]{"0","12","5-2","1-","abc"})try{TimetableData.numbers(invalid,1,11);throw new AssertionError(invalid);}catch(IllegalArgumentException good){check(true,"invalid range "+invalid);}
  try{TimetableData.monday("2026-09-08");throw new AssertionError("Tuesday");}catch(IllegalArgumentException good){check(true,"reject non-Monday semester start");}
  try{TimetableData.minutes("24:00");throw new AssertionError("24h");}catch(IllegalArgumentException good){check(true,"reject invalid lesson time");}
  System.out.println("Passed "+passed+" timetable checks");
 }
}
