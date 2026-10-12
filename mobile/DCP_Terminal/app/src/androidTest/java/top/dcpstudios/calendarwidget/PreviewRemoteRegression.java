package top.dcpstudios.calendarwidget;

import android.app.*;
import android.content.*;
import android.graphics.drawable.BitmapDrawable;
import android.media.MediaPlayer;
import android.os.Bundle;
import android.webkit.WebView;
import android.widget.*;
import org.json.JSONObject;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Opens synthetic documents through authenticated production HTTPS on the isolated emulator. */
final class PreviewRemoteRegression {
    final TerminalIntegrationInstrumentation test; final Context context; String stage="fixture";
    PreviewRemoteRegression(TerminalIntegrationInstrumentation value){test=value;context=value.getTargetContext();}
    static Object field(Object target,String name)throws Exception{Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    static Object session(MainActivity a)throws Exception{Field f=NetDiskPreview.class.getDeclaredField("OPEN");f.setAccessible(true);Map<?,?> sessions=(Map<?,?>)f.get(null);synchronized(sessions){return sessions.get(a);}}
    boolean ready(Object preview,String kind)throws Exception{
        if(preview==null)return false;
        TextView state=(TextView)field(preview,"state");String label=state.getText().toString();
        if(label.contains("无法")||label.contains("暂时"))throw new AssertionError("preview failed for synthetic "+kind);
        if(kind.equals("pdf")||kind.equals("office")||kind.equals("image")){ImageView image=(ImageView)field(preview,"image");return image!=null&&image.getDrawable() instanceof BitmapDrawable;}
        if(kind.equals("audio"))return label.equals("音频预览");
        if(kind.equals("video"))return label.equals("视频预览");
        if(kind.equals("markdown"))return label.equals("Markdown 文档预览")&&field(preview,"web")!=null&&((WebView)field(preview,"web")).getContentHeight()>0;
        return label.equals("文本预览");
    }
    Object waitReady(MainActivity a,String kind)throws Exception{
        long deadline=System.currentTimeMillis()+95000;final Object[] result={null};final Throwable[] error={null};
        while(System.currentTimeMillis()<deadline){test.runOnMainSync(()->{try{Object preview=session(a);if(ready(preview,kind))result[0]=preview;}catch(Throwable problem){error[0]=problem;}});if(error[0]!=null)throw new AssertionError(error[0]);if(result[0]!=null)return result[0];Thread.sleep(150);}
        throw new AssertionError("synthetic "+kind+" preview timed out");
    }
    void execute()throws Exception{
        byte[] bytes;try(InputStream input=new FileInputStream(new File(context.getFilesDir(),"netdisk-merge-qa.json"));ByteArrayOutputStream output=new ByteArrayOutputStream()){byte[] block=new byte[4096];int n;while((n=input.read(block))!=-1)output.write(block,0,n);bytes=output.toByteArray();}
        JSONObject fixture=new JSONObject(new String(bytes,StandardCharsets.UTF_8));JSONObject ordinary=fixture.getJSONObject("accounts").getJSONObject("ordinary");
        NetDiskSession.clear(context);NetDiskSession.prefs(context).edit().putString("origin",NetDiskSession.validateOrigin(fixture.getString("url"))).commit();CalendarStore.prefs(context).edit().putInt("interval",0).commit();TerminalClient.prefs(context).edit().putBoolean("notifications",false).putBoolean("notification_setup_seen",true).commit();
        NetDiskSession.login(context,ordinary.getString("username"),ordinary.getString("password"));
        test.activity=test.startActivitySync(new Intent(context,MainActivity.class).putExtra("page","netdisk").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));MainActivity a=(MainActivity)test.activity;
        JSONObject files=fixture.getJSONObject("preview_files");
        for(String key:Arrays.asList("pdf","word","sheet","slides","markdown","text","image","audio","video")){
            stage=key;JSONObject node=files.getJSONObject(key);String kind=NetDiskPreview.kind(node);
            test.runOnMainSync(()->NetDiskPreview.open(a,node));Object preview=waitReady(a,kind);
            test.check(true,"authenticated native "+key+" preview renders synthetic content");
            if(key.equals("pdf")){
                test.runOnMainSync(()->{try{((Button)field(preview,"next")).performClick();test.check(((TextView)field(preview,"pageLabel")).getText().toString().equals("2 / 2"),"native PDF page controls reach the second page");}catch(Exception error){throw new RuntimeException(error);}});Thread.sleep(300);
            }
            if(key.equals("markdown"))test.runOnMainSync(()->{try{WebView web=(WebView)field(preview,"web");test.check(!web.getSettings().getJavaScriptEnabled()&&!web.getSettings().getAllowFileAccess()&&web.getSettings().getBlockNetworkLoads()&&!NetDiskPreview.markdown("<script>test</script>").contains("<script>"),"Markdown reader escapes HTML and blocks scripts, file access and external loads");}catch(Exception error){throw new RuntimeException(error);}});
            if(key.equals("markdown")){
                java.util.concurrent.atomic.AtomicInteger matches=new java.util.concurrent.atomic.AtomicInteger(-1);
                test.runOnMainSync(()->{try{WebView web=(WebView)field(preview,"web");web.setFindListener((active,count,finished)->{if(finished)matches.set(count);});web.findAllAsync("Markdown preview");}catch(Exception error){throw new RuntimeException(error);}});
                long until=System.currentTimeMillis()+15000;while(matches.get()<0&&System.currentTimeMillis()<until)Thread.sleep(100);
                test.check(matches.get()>0,"Markdown's rendered document contains the actual uploaded heading");
            }
            if(key.equals("audio")){test.runOnMainSync(()->{try{((MediaPlayer)field(preview,"audio")).start();}catch(Exception error){throw new RuntimeException(error);}});Thread.sleep(400);test.runOnMainSync(()->{try{test.check(((MediaPlayer)field(preview,"audio")).getCurrentPosition()>0,"authenticated audio stream plays with native controls");}catch(Exception error){throw new RuntimeException(error);}});}
            if(key.equals("video")){test.runOnMainSync(()->{try{((VideoView)field(preview,"video")).start();}catch(Exception error){throw new RuntimeException(error);}});Thread.sleep(500);test.runOnMainSync(()->{try{test.check(((VideoView)field(preview,"video")).getCurrentPosition()>0,"authenticated video stream plays inside the APK");}catch(Exception error){throw new RuntimeException(error);}});}
            Thread.sleep(300);NativeDiskUiRegression.screenshot(test,context,"preview-"+key+".png");
            test.runOnMainSync(()->NetDiskPreview.closeAll(a));test.runOnMainSync(()->{try{test.check(session(a)==null&&!((Dialog)field(preview,"dialog")).isShowing(),"closing "+key+" preview releases its account-bound dialog");}catch(Exception error){throw new RuntimeException(error);}});
        }
        stage="logout isolation";test.runOnMainSync(()->NetDiskPreview.open(a,files.optJSONObject("image")));Object preview=waitReady(a,"image");NetDiskSession.logout(context);test.waitForIdleSync();test.runOnMainSync(()->{try{test.check(session(a)==null&&!((Dialog)field(preview,"dialog")).isShowing(),"account logout closes the previous account's preview");}catch(Exception error){throw new RuntimeException(error);}});
    }
    static void run(TerminalIntegrationInstrumentation test){PreviewRemoteRegression qa=new PreviewRemoteRegression(test);Bundle result=new Bundle();int code=Activity.RESULT_OK;
        try{qa.execute();result.putString("stream","PASS: authenticated PDF, Office, Markdown, text, image, audio and video previews\n");}
        catch(Throwable error){code=Activity.RESULT_CANCELED;result.putString("stream","FAIL: preview acceptance at "+qa.stage+" ("+error.getClass().getSimpleName()+(error instanceof AssertionError?": "+error.getMessage():"")+")\n");}
        finally{if(test.activity!=null)test.runOnMainSync(()->{NetDiskPreview.closeAll((MainActivity)test.activity);test.activity.finish();});try{NetDiskSession.logout(qa.context);}catch(Exception ignored){}new File(qa.context.getFilesDir(),"netdisk-merge-qa.json").delete();test.finish(code,result);}
    }
}
