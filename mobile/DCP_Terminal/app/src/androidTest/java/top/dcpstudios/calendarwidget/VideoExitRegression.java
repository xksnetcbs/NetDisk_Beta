package top.dcpstudios.calendarwidget;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.Activity;
import android.app.Dialog;
import android.content.Context;
import android.content.Intent;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import android.widget.ListView;
import android.widget.MediaController;
import android.widget.TextView;
import android.widget.VideoView;
import org.json.JSONObject;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;

/** Authenticated video exit and subsequent file loading, exercised through Android input. */
final class VideoExitRegression {
    private final TerminalIntegrationInstrumentation test;
    private final Context context;
    private MainActivity a;
    private String stage="fixture";
    private JSONObject videoNode, textNode;
    private AccessibilityServiceInfo originalService;

    private VideoExitRegression(TerminalIntegrationInstrumentation value){test=value;context=value.getTargetContext();}
    private interface Condition {boolean get()throws Exception;}
    private interface Target {View get()throws Exception;}
    private interface MainWork {void run()throws Exception;}
    private void main(MainWork work)throws Exception{AtomicReference<Throwable> failure=new AtomicReference<>();test.runOnMainSync(()->{try{work.run();}catch(Throwable error){failure.set(error);}});Throwable error=failure.get();if(error instanceof Exception)throw (Exception)error;if(error instanceof Error)throw (Error)error;if(error!=null)throw new AssertionError(error);}
    private static Object field(Object target,String name)throws Exception{Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    @SuppressWarnings("unchecked") private Object session()throws Exception{Field f=NetDiskPreview.class.getDeclaredField("OPEN");f.setAccessible(true);Map<MainActivity,?> sessions=(Map<MainActivity,?>)f.get(null);synchronized(sessions){return sessions.get(a);}}
    private static View text(View root,String label){if(root instanceof TextView&&label.contentEquals(((TextView)root).getText()))return root;if(root instanceof ViewGroup)for(int i=0;i<((ViewGroup)root).getChildCount();i++){View result=text(((ViewGroup)root).getChildAt(i),label);if(result!=null)return result;}return null;}
    private Dialog dialog(Object preview)throws Exception{return (Dialog)field(preview,"dialog");}
    private ListView list()throws Exception{return (ListView)field(a.netDiskScreen,"list");}
    private TextView status()throws Exception{return (TextView)field(a.netDiskScreen,"status");}

    private void await(Condition predicate,long duration,String label)throws Exception{
        long end=SystemClock.uptimeMillis()+duration;
        while(SystemClock.uptimeMillis()<end){AtomicReference<Boolean> passed=new AtomicReference<>(false);AtomicReference<Throwable> failure=new AtomicReference<>();
            test.runOnMainSync(()->{try{passed.set(predicate.get());}catch(Throwable error){failure.set(error);}});
            if(failure.get()!=null)throw new AssertionError(label+" (inspection failed)");
            if(passed.get())return;Thread.sleep(60);
        }throw new AssertionError(label);
    }
    private void touch(float x,float y)throws Exception{
        long down=SystemClock.uptimeMillis();MotionEvent first=MotionEvent.obtain(down,down,MotionEvent.ACTION_DOWN,x,y,0);first.setSource(InputDevice.SOURCE_TOUCHSCREEN);test.sendPointerSync(first);first.recycle();Thread.sleep(60);
        MotionEvent last=MotionEvent.obtain(down,SystemClock.uptimeMillis(),MotionEvent.ACTION_UP,x,y,0);last.setSource(InputDevice.SOURCE_TOUCHSCREEN);test.sendPointerSync(last);last.recycle();test.waitForIdleSync();
    }
    private int[] point(Target target,boolean required)throws Exception{int[] at=new int[2];AtomicReference<Boolean> available=new AtomicReference<>(false);main(()->{View view=target.get();if(view==null||!view.isShown()||view.getWidth()==0||view.getHeight()==0){if(required)throw new AssertionError("Visible touch target required");return;}view.getLocationOnScreen(at);at[0]+=view.getWidth()/2;at[1]+=view.getHeight()/2;available.set(true);});return available.get()?at:null;}
    private void tap(Target target)throws Exception{int[] at=point(target,true);touch(at[0],at[1]);}
    private void swipeList(boolean down)throws Exception{
        int[] rect=new int[4];main(()->{ListView view=list();view.getLocationOnScreen(rect);rect[2]=view.getWidth();rect[3]=view.getHeight();});
        float x=rect[0]+rect[2]*.45f,top=rect[1]+rect[3]*.20f,bottom=rect[1]+rect[3]*.80f,from=down?top:bottom,to=down?bottom:top;long start=SystemClock.uptimeMillis();
        for(int step=0;step<=12;step++){int action=step==0?MotionEvent.ACTION_DOWN:step==12?MotionEvent.ACTION_UP:MotionEvent.ACTION_MOVE;MotionEvent event=MotionEvent.obtain(start,SystemClock.uptimeMillis(),action,x,from+(to-from)*step/12,0);event.setSource(InputDevice.SOURCE_TOUCHSCREEN);test.sendPointerSync(event);event.recycle();Thread.sleep(25);}test.waitForIdleSync();Thread.sleep(180);
    }
    private View rowTitle(long id)throws Exception{ListView view=list();for(int i=0;i<view.getChildCount();i++){int position=view.getFirstVisiblePosition()+i;JSONObject node=(JSONObject)view.getAdapter().getItem(position);if(node.optLong("id")==id){View title=text(view.getChildAt(i),node.optString("name"));Rect visible=new Rect();if(title!=null&&title.getGlobalVisibleRect(visible)&&visible.height()>=title.getHeight()/2)return title;}}return null;}
    private void openRow(long id)throws Exception{
        await(()->list().getAdapter()!=null&&!status().getText().toString().contains("正在"),20000,"File list must finish loading before touch");
        for(int attempt=0;attempt<14;attempt++){AtomicReference<Boolean> visible=new AtomicReference<>(false);main(()->visible.set(rowTitle(id)!=null));if(visible.get()){tap(()->rowTitle(id));return;}swipeList(attempt>=7);}
        throw new AssertionError("QA row must be reachable by actual list swipes");
    }
    private Object ready(JSONObject node,String expected)throws Exception{
        AtomicReference<Object> result=new AtomicReference<>();await(()->{Object preview=session();if(preview==null)return false;if(((JSONObject)field(preview,"node")).optLong("id")!=node.optLong("id"))return false;String label=((TextView)field(preview,"state")).getText().toString();if(label.contains("无法")||label.contains("暂时"))throw new AssertionError("Authenticated preview reports loading failure");if(label.equals(expected)&&dialog(preview).isShowing()){result.set(preview);return true;}return false;},95000,"Touched file must render its authenticated preview");return result.get();
    }
    private MediaController controller(Object preview,VideoView video){
        try{return (MediaController)field(preview,"controls");}catch(Exception ignored){}
        // Older APKs keep the controller only in VideoView. This is an observation, never an action.
        try{Field f=VideoView.class.getDeclaredField("mMediaController");f.setAccessible(true);return (MediaController)f.get(video);}catch(Exception ignored){return null;}
    }
    private Rect pauseButton(){
        for(AccessibilityWindowInfo window:test.getUiAutomation().getWindows()){AccessibilityNodeInfo root=window.getRoot();if(root==null)continue;try{List<AccessibilityNodeInfo> nodes=root.findAccessibilityNodeInfosByViewId("android:id/pause");for(AccessibilityNodeInfo node:nodes)try{if(node.isVisibleToUser()){Rect bounds=new Rect();node.getBoundsInScreen(bounds);if(!bounds.isEmpty())return bounds;}}finally{node.recycle();}}finally{root.recycle();}}
        return null;
    }
    private void showControls(Object preview,VideoView video)throws Exception{
        MediaController controls=controller(preview,video);
        if((controls!=null&&!controls.isShowing())||(controls==null&&pauseButton()==null))tap(()->video);
        long until=SystemClock.uptimeMillis()+4000;while(pauseButton()==null&&SystemClock.uptimeMillis()<until)Thread.sleep(40);
        if(pauseButton()==null)throw new AssertionError("Visible native player controls required for real Play touch");
    }
    private String playerSnapshot(VideoView video){AtomicReference<String> state=new AtomicReference<>("unavailable");test.runOnMainSync(()->{try{state.set("playing="+video.isPlaying()+", position="+video.getCurrentPosition()+", duration="+video.getDuration());}catch(Throwable ignored){state.set("player observation unavailable");}});return state.get();}
    private boolean playing(VideoView video)throws Exception{AtomicReference<Boolean> result=new AtomicReference<>(false);main(()->result.set(video.isPlaying()));return result.get();}
    private String pauseDescription(){
        for(AccessibilityWindowInfo window:test.getUiAutomation().getWindows()){AccessibilityNodeInfo root=window.getRoot();if(root==null)continue;try{for(AccessibilityNodeInfo node:root.findAccessibilityNodeInfosByViewId("android:id/pause"))try{if(node.isVisibleToUser()){String description=String.valueOf(node.getContentDescription());if(description.equalsIgnoreCase("Play")||description.equalsIgnoreCase("Pause")||description.equals("播放")||description.equals("暂停"))return description;return "native player control";}}finally{node.recycle();}}finally{root.recycle();}}return "none";
    }
    private View renderedPause(MediaController controls){if(controls==null)return null;int id=context.getResources().getIdentifier("pause","id","android");View view=controls.findViewById(id);return view!=null&&view.isShown()?view:null;}
    private void touchPlay(Object preview,VideoView video)throws Exception{
        MediaController controls=controller(preview,video);Rect accessible=pauseButton();if(accessible==null){showControls(preview,video);accessible=pauseButton();}if(accessible==null)throw new AssertionError("Visible native Play button disappeared before touch");
        AtomicReference<String> bounds=new AtomicReference<>("none");main(()->{View view=renderedPause(controls);if(view!=null){int[] at=new int[2];view.getLocationOnScreen(at);bounds.set("["+at[0]+","+at[1]+" "+view.getWidth()+"x"+view.getHeight()+"]");}});
        test.progress("OBSERVED native Play before touch: "+playerSnapshot(video)+", node="+pauseDescription()+", accessibility bounds="+accessible.toShortString()+", rendered bounds="+bounds.get());
        // Read fresh coordinates only after diagnostics. Never take a screenshot before Play input.
        boolean touched=false;for(int attempt=0;attempt<2;attempt++){
            if(playing(video)){test.progress("OBSERVED video already playing; actual Pause touch skipped");return;}
            if(controls!=null){int[] at=point(()->renderedPause(controls),false);if(at!=null){touch(at[0],at[1]);touched=true;break;}}
            else{Rect fresh=pauseButton();if(fresh!=null){touch(fresh.exactCenterX(),fresh.exactCenterY());touched=true;break;}}
            // Showing a hidden controller uses an actual video touch, without another Play press.
            showControls(preview,video);
        }
        if(!touched)throw new AssertionError("Native Play button must remain visible for actual input");
        test.progress("OBSERVED native Play after touch: "+playerSnapshot(video)+", node="+pauseDescription());
        NativeDiskUiRegression.screenshot(test,context,"video-exit-controls.png");
    }
    private void startPlaying(Object preview)throws Exception{
        VideoView video=(VideoView)field(preview,"video");test.progress("OBSERVED video before controls: "+playerSnapshot(video));showControls(preview,video);
        if(playing(video))test.progress("OBSERVED video already playing; actual Pause touch skipped");else touchPlay(preview,video);
        try{await(()->video.isPlaying()&&video.getCurrentPosition()>200,6000,"Actual player Play touch must advance the authenticated video");}catch(AssertionError failure){test.progress("OBSERVED video after Play deadline: "+playerSnapshot(video)+", node="+pauseDescription());throw failure;}
        main(()->test.check(video.getDuration()>=8000&&video.getCurrentPosition()<video.getDuration()-1000,"video is playing before its natural end when the user exits"));
        showControls(preview,video);
    }
    private void backState(Object preview,VideoView video,MediaController controls,String label)throws Exception{
        AtomicReference<String> state=new AtomicReference<>();main(()->{String playback="none";if(video!=null)try{playback=Boolean.toString(video.isPlaying());}catch(RuntimeException ignored){playback="unavailable";}View decor=preview==null?null:dialog(preview).getWindow().getDecorView();boolean sameToken=controls!=null&&decor!=null&&controls.getWindowToken()!=null&&controls.getWindowToken()==decor.getWindowToken();state.set("currentSession="+(session()==preview)+", dialogShowing="+(preview!=null&&dialog(preview).isShowing())+", page="+a.page+", controlsShowing="+(controls!=null&&controls.isShowing())+", videoPlaying="+playback+", dialogFocus="+(decor!=null&&decor.hasWindowFocus())+", controlsFocus="+(controls!=null&&controls.hasWindowFocus())+", controlsTokenEqualsDialog="+sameToken);});
        Rect button=pauseButton();test.progress("OBSERVED "+label+": "+state.get()+", pauseBounds="+(button==null?"none":button.toShortString())+", "+pauseFocus());
    }
    private String pauseFocus(){
        for(AccessibilityWindowInfo window:test.getUiAutomation().getWindows()){AccessibilityNodeInfo root=window.getRoot();if(root==null)continue;try{for(AccessibilityNodeInfo node:root.findAccessibilityNodeInfosByViewId("android:id/pause"))try{if(node.isVisibleToUser())return "pauseWindowFocused="+window.isFocused()+", pauseWindowActive="+window.isActive();}finally{node.recycle();}}finally{root.recycle();}}return "pauseWindow=none";
    }
    private void injectBack(String label)throws Exception{
        long downTime=SystemClock.uptimeMillis();KeyEvent down=new KeyEvent(downTime,downTime,KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_BACK,0,0,KeyCharacterMap.VIRTUAL_KEYBOARD,0,KeyEvent.FLAG_FROM_SYSTEM,InputDevice.SOURCE_KEYBOARD);
        test.check(test.getUiAutomation().injectInputEvent(down,true),label+" BACK DOWN input injection succeeds");Thread.sleep(60);
        KeyEvent up=new KeyEvent(downTime,SystemClock.uptimeMillis(),KeyEvent.ACTION_UP,KeyEvent.KEYCODE_BACK,0,0,KeyCharacterMap.VIRTUAL_KEYBOARD,0,KeyEvent.FLAG_FROM_SYSTEM,InputDevice.SOURCE_KEYBOARD);
        test.check(test.getUiAutomation().injectInputEvent(up,true),label+" BACK UP input injection succeeds");test.waitForIdleSync();
    }
    private void noOverlay(MediaController oldControls,String mode,Object preview,VideoView video)throws Exception{
        // Test immediately, before MediaController's normal automatic hide timeout can mask a leak.
        long until=SystemClock.uptimeMillis()+600;while((pauseButton()!=null||(oldControls!=null&&oldControls.isShowing()))&&SystemClock.uptimeMillis()<until)Thread.sleep(40);
        if(pauseButton()!=null||(oldControls!=null&&oldControls.isShowing()))backState(preview,video,oldControls,mode+" overlay deadline");
        test.check(pauseButton()==null&&(oldControls==null||!oldControls.isShowing()),mode+" removes the visible player control window immediately");
    }
    private void verifyClosed(Object old,VideoView oldVideo,MediaController oldControls,String mode)throws Exception{
        await(()->session()==null&&!dialog(old).isShowing(),4000,mode+" must dismiss the preview through real device input");noOverlay(oldControls,mode,old,oldVideo);
        main(()->test.check(!oldVideo.isPlaying(),mode+" stops the previous video's playback"));
    }
    private void refreshAndReopenVideo()throws Exception{
        stage="refresh after video exit";AtomicReference<Object> previous=new AtomicReference<>();main(()->previous.set(list().getAdapter()));
        tap(()->NativeDiskUiRegression.described(a.root,"刷新"));await(()->list().getAdapter()!=previous.get()&&!status().getText().toString().contains("正在")&&!status().getText().toString().contains("重试"),20000,"Actual Refresh touch must fetch the subsequent file list");
        test.check(true,"file list loads successfully after interrupted video playback");stage="video reopen";openRow(videoNode.getLong("id"));Object reopened=ready(videoNode,"视频预览");startPlaying(reopened);test.check(true,"actual file title touch reopens and plays the same video after exit");
        VideoView reopenedVideo=(VideoView)field(reopened,"video");MediaController reopenedControls=controller(reopened,reopenedVideo);tap(()->text(dialog(reopened).getWindow().getDecorView(),"关闭"));verifyClosed(reopened,reopenedVideo,reopenedControls,"reopened video Close touch");
    }
    private void textAfterExit()throws Exception{
        stage="text after video exit";openRow(textNode.getLong("id"));Object text=ready(textNode,"文本预览");test.check(TerminalIntegrationInstrumentation.textPresent(dialog(text).getWindow().getDecorView(),"AFTER VIDEO EXIT FILE PREVIEW OK"),"actual subsequent text file touch renders authenticated file bytes after video exit");NativeDiskUiRegression.screenshot(test,context,"video-exit-text.png");
        tap(()->text(dialog(text).getWindow().getDecorView(),"关闭"));await(()->session()==null,4000,"Text preview Close touch must restore the browser");
    }
    private void closeDuringPreparation()throws Exception{
        stage="video preparation Close touch";openRow(videoNode.getLong("id"));AtomicReference<Object> opened=new AtomicReference<>();AtomicReference<Boolean> preparing=new AtomicReference<>(false);
        await(()->{Object preview=session();if(preview==null)return false;opened.set(preview);preparing.set(!((TextView)field(preview,"state")).getText().toString().equals("视频预览"));return dialog(preview).isShowing();},4000,"Video dialog must appear before immediate Close touch");
        Object preview=opened.get();tap(()->text(dialog(preview).getWindow().getDecorView(),"关闭"));await(()->session()==null&&!dialog(preview).isShowing(),4000,"Immediate Close touch must dismiss a preparing video dialog");Thread.sleep(1500);noOverlay(null,"immediate Close touch",preview,(VideoView)field(preview,"video"));
        test.check(true,"immediate video Close touch leaves no delayed preview or control window");
        test.progress(preparing.get()?"OBSERVED video was still preparing when the dialog was first inspected; input may complete after preparation":"OBSERVED preparation completed before the first dialog inspection; immediate-close path remains covered");
        textAfterExit();
    }
    private void execute()throws Exception{
        byte[] bytes;try(InputStream input=new FileInputStream(new File(context.getFilesDir(),"netdisk-merge-qa.json"));ByteArrayOutputStream output=new ByteArrayOutputStream()){byte[] block=new byte[4096];int n;while((n=input.read(block))!=-1)output.write(block,0,n);bytes=output.toByteArray();}
        JSONObject fixture=new JSONObject(new String(bytes,StandardCharsets.UTF_8));JSONObject account=fixture.getJSONObject("accounts").getJSONObject("ordinary");videoNode=fixture.getJSONObject("preview_files").getJSONObject("video");textNode=fixture.getJSONObject("preview_files").getJSONObject("text");
        originalService=test.getUiAutomation().getServiceInfo();AccessibilityServiceInfo service=test.getUiAutomation().getServiceInfo();service.flags|=AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS|AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS;test.getUiAutomation().setServiceInfo(service);
        NetDiskSession.clear(context);NetDiskSession.prefs(context).edit().putString("origin",NetDiskSession.validateOrigin(fixture.getString("url"))).commit();CalendarStore.prefs(context).edit().putInt("interval",0).commit();TerminalClient.prefs(context).edit().putBoolean("notifications",false).putBoolean("notification_setup_seen",true).commit();NetDiskSession.login(context,account.getString("username"),account.getString("password"));
        test.activity=test.startActivitySync(new Intent(context,MainActivity.class).putExtra("page","netdisk").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));a=(MainActivity)test.activity;test.waitForIdleSync();
        stage="project navigation";long project=videoNode.optLong("project_id",fixture.optLong("project_id",0));if(project==0)tap(()->NativeDiskUiRegression.described(a.root,"个人文件"));else openRow(project);
        closeDuringPreparation();stage="video Close touch";openRow(videoNode.getLong("id"));Object first=ready(videoNode,"视频预览");startPlaying(first);VideoView oldVideo=(VideoView)field(first,"video");MediaController oldControls=controller(first,oldVideo);NativeDiskUiRegression.screenshot(test,context,"video-exit-playing.png");showControls(first,oldVideo);
        tap(()->text(dialog(first).getWindow().getDecorView(),"关闭"));verifyClosed(first,oldVideo,oldControls,"Close touch during playback");refreshAndReopenVideo();textAfterExit();
        stage="video BACK key";openRow(videoNode.getLong("id"));Object second=ready(videoNode,"视频预览");startPlaying(second);VideoView secondVideo=(VideoView)field(second,"video");MediaController secondControls=controller(second,secondVideo);
        // Let the newly shown floating window receive focus before dispatching physical BACK.
        test.getUiAutomation().waitForIdle(200,5000);Thread.sleep(150);
        backState(second,secondVideo,secondControls,"before first BACK");showControls(second,secondVideo);
        test.check(pauseButton()!=null&&(secondControls==null||secondControls.isShowing()),"player controls remain visibly open immediately before the first BACK input");
        injectBack("first");backState(second,secondVideo,secondControls,"first BACK result");
        // Android MediaController consumes one BACK to hide its controls; a second closes the dialog.
        noOverlay(secondControls,"first BACK with controls visible",second,secondVideo);main(()->test.check(session()==second&&dialog(second).isShowing(),"first BACK hides player controls while preserving the current preview"));
        // Floating window removal returns focus asynchronously. Match a user's pause between keys.
        test.getUiAutomation().waitForIdle(200,5000);Thread.sleep(150);
        backState(second,secondVideo,secondControls,"before second BACK");injectBack("second");backState(second,secondVideo,secondControls,"second BACK result");
        verifyClosed(second,secondVideo,secondControls,"BACK during playback");refreshAndReopenVideo();textAfterExit();
        test.getUiAutomation().waitForIdle(200,5000);Thread.sleep(250);NativeDiskUiRegression.screenshot(test,context,"video-exit-browser.png");
    }
    static void run(TerminalIntegrationInstrumentation test){VideoExitRegression qa=new VideoExitRegression(test);Bundle result=new Bundle();int outcome=Activity.RESULT_OK;
        try{qa.execute();result.putString("stream","PASS: actual authenticated video Play, interrupted Close/BACK, no residual controls, list refresh, repeated video and text preview\n");}
        catch(Throwable error){outcome=Activity.RESULT_CANCELED;result.putString("stream","FAIL: video exit at "+qa.stage+" ("+error.getClass().getSimpleName()+(error instanceof AssertionError?": "+error.getMessage():"")+")\n");try{NativeDiskUiRegression.screenshot(test,qa.context,"video-exit-failure.png");}catch(Exception ignored){}}
        finally{if(qa.a!=null)try{qa.main(()->{NetDiskPreview.closeAll(qa.a);qa.a.finish();});}catch(Throwable ignored){}try{NetDiskSession.logout(qa.context);}catch(Exception ignored){}new File(qa.context.getFilesDir(),"netdisk-merge-qa.json").delete();if(qa.originalService!=null)test.getUiAutomation().setServiceInfo(qa.originalService);test.activity=null;test.finish(outcome,result);}
    }
}
