package top.dcpstudios.calendarwidget;

import android.app.AlertDialog;
import android.content.*;
import android.graphics.Bitmap;
import android.view.*;
import android.widget.*;
import java.io.*;
import java.lang.reflect.Field;
import java.util.*;
import org.json.JSONObject;

/** Real native layout and input checks for the compact disk surface. */
final class NativeDiskUiRegression {
    static View described(View view,String description){if(view.getContentDescription()!=null&&description.contentEquals(view.getContentDescription()))return view;if(view instanceof ViewGroup)for(int i=0;i<((ViewGroup)view).getChildCount();i++){View result=described(((ViewGroup)view).getChildAt(i),description);if(result!=null)return result;}return null;}
    static boolean controls(View view,int minimum){if("netdisk-control".equals(view.getTag())&&(view.getWidth()<minimum||view.getHeight()<minimum||view.getContentDescription()==null))return false;if(view instanceof ViewGroup)for(int i=0;i<((ViewGroup)view).getChildCount();i++)if(!controls(((ViewGroup)view).getChildAt(i),minimum))return false;return true;}
    static boolean lineIcons(View view){if(view instanceof TextView){String text=((TextView)view).getText().toString();if(text.matches(".*[▦▤▧›⋯●].*"))return false;}if(view instanceof ViewGroup)for(int i=0;i<((ViewGroup)view).getChildCount();i++)if(!lineIcons(((ViewGroup)view).getChildAt(i)))return false;return true;}
    static Object field(NetDiskScreen screen,String name)throws Exception{Field f=NetDiskScreen.class.getDeclaredField(name);f.setAccessible(true);return f.get(screen);}
    @SuppressWarnings("unchecked") static AlertDialog active(NetDiskScreen screen)throws Exception{for(AlertDialog dialog:(List<AlertDialog>)field(screen,"dialogs"))if(dialog.isShowing())return dialog;throw new AssertionError("Expected native action dialog");}
    @SuppressWarnings("unchecked") static void rows(NetDiskScreen screen,JSONObject...rows)throws Exception{Field f=NetDiskScreen.class.getDeclaredField("items");f.setAccessible(true);f.set(screen,new ArrayList<>(Arrays.asList(rows)));java.lang.reflect.Method render=NetDiskScreen.class.getDeclaredMethod("renderItems");render.setAccessible(true);render.invoke(screen);}
    static void screenshot(TerminalIntegrationInstrumentation test,Context c,String name)throws Exception{Bitmap image=test.getUiAutomation().takeScreenshot();if(image==null)throw new AssertionError("Native disk screenshot unavailable");try(OutputStream out=new FileOutputStream(new File(c.getFilesDir(),name))){image.compress(Bitmap.CompressFormat.PNG,100,out);}finally{image.recycle();}}
    static void run(TerminalIntegrationInstrumentation test,Context c)throws Exception{
        NetDiskSession.observeWebLogin(c,true);test.activity=test.startActivitySync(new Intent(c,MainActivity.class).putExtra("page","netdisk").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));test.waitForIdleSync();test.getUiAutomation().waitForIdle(250,5000);MainActivity a=(MainActivity)test.activity;
        test.runOnMainSync(()->test.check(controls(a.root,a.d(44))&&TerminalIntegrationInstrumentation.findWeb(a.root)==null,"compact native login preserves 44dp controls, accessible labels and no browser container"));screenshot(test,c,"native-login-compact.png");
        NetDiskRaceRegression.identity(test,c,true);test.runOnMainSync(a::netdisk);TerminalClient.IO.submit(()->{}).get();test.waitForIdleSync();NetDiskScreen screen=a.netDiskScreen;
        JSONObject folder=new JSONObject().put("id",921).put("type","folder").put("name","设计资料");JSONObject file=new JSONObject().put("id",922).put("type","file").put("name","项目设计说明.pdf").put("mime_type","application/pdf").put("size_bytes",16384);JSONObject image=new JSONObject().put("id",923).put("type","file").put("name","产品预览.png").put("mime_type","image/png").put("size_bytes",45612);
        test.runOnMainSync(()->{try{((List<JSONObject>)field(screen,"folders")).add(new JSONObject().put("id",920).put("name","验收项目"));Field project=NetDiskScreen.class.getDeclaredField("projectId");project.setAccessible(true);project.setLong(screen,926);Field name=NetDiskScreen.class.getDeclaredField("projectName");name.setAccessible(true);name.set(screen,"验收项目");screen.show();}catch(Exception e){throw new RuntimeException(e);}});TerminalClient.IO.submit(()->{}).get();test.waitForIdleSync();
        test.runOnMainSync(()->{try{rows(screen,folder,file,image);}catch(Exception e){throw new RuntimeException(e);}});test.waitForIdleSync();test.getUiAutomation().waitForIdle(250,5000);
        test.runOnMainSync(()->test.check(controls(a.root,a.d(44))&&lineIcons((View)fieldUnchecked(screen,"content"))&&TerminalIntegrationInstrumentation.findWeb(a.root)==null,"native file rows use outline symbols and all compact controls retain 44dp touch targets"));screenshot(test,c,"native-disk-compact.png");
        test.runOnMainSync(()->test.check(described(a.root,"上传文件")!=null&&described(a.root,"新建文件夹")!=null&&described(a.root,"返回上一级")!=null&&described(a.root,"刷新")!=null,"compact file browser retains upload, new-folder, parent and refresh actions"));
        test.runOnMainSync(()->{try{EditText search=(EditText)field(screen,"search");search.setText("说明");test.check(((ListView)field(screen,"list")).getAdapter().getCount()==1,"native search filters the actual file list immediately");search.setText("");}catch(Exception e){throw new RuntimeException(e);}});
        test.waitForIdleSync();test.getUiAutomation().waitForIdle(250,5000);
        test.runOnMainSync(()->{View menu=described(a.root,"项目设计说明.pdf 文件操作");if(menu==null)throw new AssertionError("File actions must be present after clearing native search");menu.performClick();});
        test.runOnMainSync(()->{try{View menu=active(screen).getWindow().getDecorView();test.check(TerminalIntegrationInstrumentation.textPresent(menu,"预览")&&TerminalIntegrationInstrumentation.textPresent(menu,"下载 / 保存到设备")&&TerminalIntegrationInstrumentation.textPresent(menu,"打开文件")&&TerminalIntegrationInstrumentation.textPresent(menu,"详细信息")&&TerminalIntegrationInstrumentation.textPresent(menu,"重命名")&&TerminalIntegrationInstrumentation.textPresent(menu,"移动")&&TerminalIntegrationInstrumentation.textPresent(menu,"删除"),"native outline action menu retains preview, save, open and every file management operation");described(menu,"重命名").performClick();AlertDialog rename=active(screen);screen.logout();test.check(!rename.isShowing(),"account logout dismisses old file action dialogs before they can mutate a new account");}catch(Exception e){throw new RuntimeException(e);}});
        test.runOnMainSync(a::finish);test.activity=null;
    }
    static Object fieldUnchecked(NetDiskScreen screen,String name){try{return field(screen,name);}catch(Exception e){throw new RuntimeException(e);}}
}
