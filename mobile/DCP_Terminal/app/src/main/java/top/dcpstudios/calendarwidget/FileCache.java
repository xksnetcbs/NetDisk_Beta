package top.dcpstudios.calendarwidget;
import android.content.Context;
import java.io.File;
/** Previously opened private files never remain available after an account switch. */
final class FileCache {
    static void clear(Context c){File opened=new File(c.getCacheDir(),"opened");File[] files=opened.listFiles();if(files!=null)for(File file:files)if(file.isFile())file.delete();opened.delete();}
}
