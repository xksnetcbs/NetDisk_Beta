package top.dcpstudios.calendarwidget;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Dialog;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.ViewGroup;
import android.widget.ListView;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.lang.reflect.Field;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;

/** Uses Android's input dispatcher for every browser click; no performClick or direct navigation. */
final class NetDiskClickRegression {
    private static final long PROJECT=701, ROOT=801, FOLDER=802, TEXT=803;
    private static final String PROJECT_NAME="Touch regression project", FOLDER_NAME="Touch regression folder";
    private static final String FILE_NAME="Touch regression text.txt", FILE_CONTENT="NATIVE TOUCH PREVIEW CONTENT";
    private static volatile int rootRequests, folderRequests, previewRequests;
    private static MainActivity a;
    private static TerminalIntegrationInstrumentation test;

    interface Condition { boolean get() throws Exception; }
    static Object field(Object target,String name)throws Exception {Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    private static JSONObject node(long id,String name,String type)throws Exception{return new JSONObject().put("id",id).put("name",name).put("type",type).put("mime_type",type.equals("file")?"text/plain":"").put("size_bytes",FILE_CONTENT.length());}
    private static JSONObject project()throws Exception{return new JSONObject().put("id",PROJECT).put("name",PROJECT_NAME).put("key","TOUCH_FIXTURE").put("role","creator").put("description","Isolated touch fixture");}

    private static final class Response extends HttpURLConnection {
        private byte[] body; private int status=200;
        Response(URL url){super(url);}
        @Override public void connect(){}
        @Override public void disconnect(){}
        @Override public boolean usingProxy(){return false;}
        @Override public OutputStream getOutputStream(){return new ByteArrayOutputStream();}
        @Override public Map<String,List<String>> getHeaderFields(){return Collections.emptyMap();}
        private void prepare(){if(body!=null)return;try{
            String path=url.getPath();JSONObject data=new JSONObject();
            if(path.equals("/api/auth/refresh"))data.put("access_token","isolated-native-access-11").put("user",new JSONObject().put("id",11).put("username","touch-fixture").put("role_system","user"));
            else if(path.equals("/api/projects"))data.put("items",new JSONArray().put(project())).put("total",1);
            else if(path.equals("/api/files/root")){rootRequests++;data.put("root",node(ROOT,"Project root","folder"));}
            else if(path.equals("/api/files")){
                boolean nested=url.getQuery()!=null&&url.getQuery().contains("parent_id="+FOLDER);
                if(nested){folderRequests++;data.put("items",new JSONArray().put(node(TEXT,FILE_NAME,"file")));}
                else data.put("items",new JSONArray().put(node(FOLDER,FOLDER_NAME,"folder")).put(node(TEXT,FILE_NAME,"file")));
            }else if(path.equals("/api/files/"+TEXT+"/preview")){previewRequests++;body=FILE_CONTENT.getBytes(StandardCharsets.UTF_8);return;}
            else if(path.equals("/api/mobile/terminal/snapshot")||path.equals("/api/mobile/terminal/schedules"))data.put("netdisk_user_id",11).put("terminal_access",false).put("schedules",new JSONArray()).put("messages",new JSONArray()).put("cursor",0);
            else if(path.equals("/api/mobile/terminal/desktop/messages"))data.put("items",new JSONArray()).put("more",false);
            else if(!path.equals("/api/mobile/terminal/attention")&&!path.equals("/api/auth/logout")){status=404;}
            body=new JSONObject().put("ok",status==200).put("data",data).toString().getBytes(StandardCharsets.UTF_8);
        }catch(Exception error){throw new IllegalStateException(error);}}
        @Override public int getResponseCode(){prepare();return status;}
        @Override public InputStream getInputStream(){prepare();return new ByteArrayInputStream(body);}
        @Override public InputStream getErrorStream(){return getInputStream();}
        @Override public String getHeaderField(String name){prepare();return name.equalsIgnoreCase("Content-Length")?Integer.toString(body.length):null;}
    }
    private static void install(){URL.setURLStreamHandlerFactory(protocol->"https".equals(protocol)?new URLStreamHandler(){@Override protected URLConnection openConnection(URL url){return new Response(url);}}:null);}

    private static void await(Condition predicate,String label)throws Exception{
        long deadline=SystemClock.uptimeMillis()+7000;Throwable last=null;
        while(SystemClock.uptimeMillis()<deadline){AtomicReference<Boolean> pass=new AtomicReference<>(false);AtomicReference<Throwable> failure=new AtomicReference<>();
            test.runOnMainSync(()->{try{pass.set(predicate.get());}catch(Throwable error){failure.set(error);}});
            if(pass.get()){test.waitForIdleSync();return;}last=failure.get();Thread.sleep(60);
        }throw new AssertionError(label+(last==null?"":" ("+last+")"));
    }
    private static View text(View root,String value){if(root instanceof TextView&&value.contentEquals(((TextView)root).getText()))return root;if(root instanceof ViewGroup)for(int i=0;i<((ViewGroup)root).getChildCount();i++){View match=text(((ViewGroup)root).getChildAt(i),value);if(match!=null)return match;}return null;}
    private static ListView list()throws Exception{return (ListView)field(a.netDiskScreen,"list");}
    private static View row(String name)throws Exception{ListView list=list();for(int i=0;i<list.getChildCount();i++)if(text(list.getChildAt(i),name)!=null)return list.getChildAt(i);throw new AssertionError("Visible file row missing: "+name);}
    private static View rowText(String name)throws Exception{View value=text(row(name),name);if(value==null)throw new AssertionError("Row text missing");return value;}
    private static int depth()throws Exception{return ((List<?>)field(a.netDiskScreen,"folders")).size();}
    @SuppressWarnings("unchecked") private static AlertDialog actions()throws Exception{for(AlertDialog dialog:(List<AlertDialog>)field(a.netDiskScreen,"dialogs"))if(dialog.isShowing())return dialog;return null;}
    @SuppressWarnings("unchecked") private static Dialog preview()throws Exception{Field f=NetDiskPreview.class.getDeclaredField("OPEN");f.setAccessible(true);Map<MainActivity,?> sessions=(Map<MainActivity,?>)f.get(null);Object session=sessions.get(a);return session==null?null:(Dialog)field(session,"dialog");}
    private static boolean readyPreview()throws Exception{Dialog d=preview();return d!=null&&d.isShowing()&&text(d.getWindow().getDecorView(),FILE_CONTENT)!=null;}

    /** Derive device screen coordinates from the rendered view, then send real down/up events. */
    private static void touch(ConditionView target,boolean hold)throws Exception{
        AtomicReference<View> selected=new AtomicReference<>();int[] point=new int[2];
        test.runOnMainSync(()->{try{View view=target.get();if(view==null||!view.isShown()||view.getWidth()==0||view.getHeight()==0)throw new AssertionError("Tap target is not laid out");selected.set(view);view.getLocationOnScreen(point);point[0]+=view.getWidth()/2;point[1]+=view.getHeight()/2;}catch(Exception error){throw new RuntimeException(error);}});
        long down=SystemClock.uptimeMillis();MotionEvent start=MotionEvent.obtain(down,down,MotionEvent.ACTION_DOWN,point[0],point[1],0);start.setSource(InputDevice.SOURCE_TOUCHSCREEN);test.sendPointerSync(start);start.recycle();
        Thread.sleep(hold?ViewConfiguration.getLongPressTimeout()+180:70);
        MotionEvent end=MotionEvent.obtain(down,SystemClock.uptimeMillis(),MotionEvent.ACTION_UP,point[0],point[1],0);end.setSource(InputDevice.SOURCE_TOUCHSCREEN);test.sendPointerSync(end);end.recycle();test.waitForIdleSync();
    }
    interface ConditionView {View get()throws Exception;}
    private static void tap(ConditionView target)throws Exception{touch(target,false);}
    private static void closeActions()throws Exception{tap(()->actions().getButton(AlertDialog.BUTTON_NEGATIVE));await(()->actions()==null,"Action dialog must dismiss after actual Close touch");}
    private static void closePreview()throws Exception{tap(()->text(preview().getWindow().getDecorView(),"关闭"));await(()->preview()==null,"Preview must dismiss after actual Close touch");}
    private static void up()throws Exception{tap(()->NativeDiskUiRegression.described(a.root,"返回上一级"));}
    private static void screenshot(Context c,String name)throws Exception{Bitmap image=test.getUiAutomation().takeScreenshot();if(image==null)throw new AssertionError("Touch screenshot unavailable");try(OutputStream out=new FileOutputStream(new File(c.getFilesDir(),name))){image.compress(Bitmap.CompressFormat.PNG,100,out);}finally{image.recycle();}}

    static void run(TerminalIntegrationInstrumentation instrumentation){test=instrumentation;Bundle result=new Bundle();int outcome=Activity.RESULT_OK;Context c=test.getTargetContext();
        try{
            install();rootRequests=folderRequests=previewRequests=0;
            NetDiskSession.prefs(c).edit().putString("origin","https://127.0.0.1:1").commit();CalendarStore.prefs(c).edit().putInt("interval",0).commit();TerminalClient.prefs(c).edit().putBoolean("notifications",false).putBoolean("notification_setup_seen",true).commit();
            NetDiskRaceRegression.identity(test,c,false);test.activity=test.startActivitySync(new Intent(c,MainActivity.class).putExtra("page","netdisk").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));a=(MainActivity)test.activity;test.waitForIdleSync();
            await(()->text(a.root,PROJECT_NAME)!=null,"Project fixture must load through native HTTP API");test.check(rootRequests==0,"disk touch fixture loads project list without direct root navigation");

            tap(()->rowText(PROJECT_NAME));await(()->depth()==1&&text(a.root,FOLDER_NAME)!=null,"Actual project title tap must open the project");test.check(rootRequests==1,"actual screen touch on project title enters its API root");
            tap(()->rowText(FOLDER_NAME));await(()->depth()==2&&text(a.root,FOLDER_NAME)==null&&text(a.root,FILE_NAME)!=null,"Actual folder title tap must open the folder");test.check(folderRequests>0,"actual screen touch on folder title loads its child files");
            up();await(()->depth()==1&&text(a.root,FOLDER_NAME)!=null,"Parent toolbar touch must return to project root");test.check(depth()==1,"actual parent button touch returns from folder to project root");
            tap(()->((ViewGroup)row(FOLDER_NAME)).getChildAt(0));await(()->depth()==2&&text(a.root,FOLDER_NAME)==null,"Actual folder icon tap must open the folder");test.check(depth()==2,"folder icon remains part of the tappable ListView row");up();await(()->depth()==1&&text(a.root,FOLDER_NAME)!=null,"Folder icon path can return");

            tap(()->rowText(FILE_NAME));await(NetDiskClickRegression::readyPreview,"Actual file title tap must open and load text preview");test.check(previewRequests==1,"actual file title touch fetches and renders preview bytes");screenshot(c,"disk-click-preview.png");closePreview();
            tap(()->NativeDiskUiRegression.described(row(FILE_NAME),FILE_NAME+" 文件操作"));await(()->actions()!=null,"Actual file menu touch must open actions");test.check(depth()==1&&previewRequests==1,"right file menu touch opens actions without firing row preview");
            tap(()->NativeDiskUiRegression.described(actions().getWindow().getDecorView(),"预览"));await(NetDiskClickRegression::readyPreview,"Actual Preview action touch must load preview");test.check(previewRequests==2,"actual action-menu Preview touch renders the same file");closePreview();
            touch(()->rowText(FILE_NAME),true);await(()->actions()!=null,"Actual long press must open file actions");test.check(previewRequests==2&&text(actions().getWindow().getDecorView(),"详细信息")!=null,"file row long press opens management actions without opening preview");closeActions();

            up();await(()->depth()==0&&text(a.root,PROJECT_NAME)!=null,"Project parent touch must return to project list");test.check(rootRequests==1,"actual project parent touch restores the project list");
            tap(()->NativeDiskUiRegression.described(row(PROJECT_NAME),PROJECT_NAME+" 项目操作"));await(()->actions()!=null,"Actual project menu touch must open project details");test.check(rootRequests==1&&text(actions().getWindow().getDecorView(),"打开文件")!=null,"right project menu opens details without entering the project");closeActions();
            touch(()->rowText(PROJECT_NAME),true);await(()->actions()!=null,"Actual project long press must open details");test.check(rootRequests==1,"project row long press independently opens project details");closeActions();
            tap(()->text(row(PROJECT_NAME),"TOUCH_FIXTURE · 创建者"));await(()->depth()==1&&text(a.root,FOLDER_NAME)!=null,"Actual project subtitle tap must enter project");test.check(rootRequests==2,"project subtitle remains part of the tappable ListView row");
            screenshot(c,"disk-click-browser.png");test.check(TerminalIntegrationInstrumentation.findWeb(a.root)==null,"touch navigation and text preview leave the browser native");
            result.putString("stream","PASS: actual MotionEvent project/folder/file taps, parent navigation, preview, independent menu and long press\n");
        }catch(Throwable error){outcome=Activity.RESULT_CANCELED;result.putString("stream","FAIL: "+error+"\n");error.printStackTrace();try{screenshot(c,"disk-click-failure.png");}catch(Exception ignored){}}
        finally{if(a!=null)test.runOnMainSync(()->{NetDiskPreview.closeAll(a);a.finish();});NetDiskSession.observeWebLogin(c,true);test.activity=null;test.finish(outcome,result);}
    }
}
