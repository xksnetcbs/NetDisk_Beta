package top.dcpstudios.calendarwidget;

import android.content.Context;
import android.net.Uri;
import android.database.Cursor;
import android.provider.OpenableColumns;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.net.HttpURLConnection;
import java.util.*;

/** Native file operations use the same account-bound API as the web client. */
final class NetDiskFiles {
    interface Progress { void update(String text); }
    static JSONObject json(Context c,String path,String method,JSONObject body,NetDiskSession.Account account)throws Exception {
        return NetDiskSession.requestMethod(c,path,method,body,account).data;
    }
    static List<JSONObject> projects(Context c,NetDiskSession.Account account)throws Exception {
        List<JSONObject> result=new ArrayList<>();int page=1,total;
        do{JSONObject data=json(c,"/api/projects?page="+page+"&page_size=100","GET",null,account);JSONArray rows=data.getJSONArray("items");
            if(rows.length()==0)break;
            for(int i=0;i<rows.length();i++)result.add(rows.getJSONObject(i));total=data.getInt("total");page++;
        }while(result.size()<total);
        return result;
    }
    static JSONObject root(Context c,long project,NetDiskSession.Account account)throws Exception {
        return json(c,"/api/files/root?scope="+(project>0?"project&project_id="+project:"personal"),"GET",null,account).getJSONObject("root");
    }
    static List<JSONObject> list(Context c,long parent,NetDiskSession.Account account)throws Exception {
        JSONArray rows=json(c,"/api/files?parent_id="+parent,"GET",null,account).getJSONArray("items");List<JSONObject> result=new ArrayList<>();
        for(int i=0;i<rows.length();i++)result.add(rows.getJSONObject(i));
        Collections.sort(result,(a,b)->{int folder=Boolean.compare(!"folder".equals(a.optString("type")),!"folder".equals(b.optString("type")));return folder!=0?folder:a.optString("name").compareToIgnoreCase(b.optString("name"));});return result;
    }
    static JSONObject createFolder(Context c,long parent,long project,String name,NetDiskSession.Account account)throws Exception {
        JSONObject body=new JSONObject().put("name",name).put("parent_id",parent).put("scope",project>0?"project":"personal");
        if(project>0)body.put("project_id",project);
        return json(c,"/api/files/folders","POST",body,account).getJSONObject("folder");
    }
    static String filename(Context c,Uri uri) {
        if("file".equals(uri.getScheme()))return new File(uri.getPath()).getName();
        try(Cursor cursor=c.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)) {
            if(cursor!=null&&cursor.moveToFirst()&&!cursor.isNull(0)&&!cursor.getString(0).trim().isEmpty())return cursor.getString(0);
        }catch(Exception ignored){}return "文件";
    }
    static JSONObject upload(Context c,Uri uri,long parent,long project,NetDiskSession.Account account,Progress progress)throws Exception {
        File local=null;String sessionId=null;boolean complete=false;
        try{
            String name=filename(c,uri),mime=c.getContentResolver().getType(uri);long size=length(c,uri);
            progress.update("正在准备 "+name);
            if(size<0){local=File.createTempFile("upload-",".part",c.getCacheDir());size=0;
                try(InputStream input=c.getContentResolver().openInputStream(uri);OutputStream output=new FileOutputStream(local)) {
                    if(input==null)throw new IOException("无法读取所选文件");byte[] buffer=new byte[65536];int n;
                    while((n=input.read(buffer))!=-1){NetDiskSession.guard(c,account,()->{});output.write(buffer,0,n);size+=n;}
                }
            }
            if(size==0)return emptyUpload(c,name,mime,parent,project,account);
            int chunkSize=1024*1024;
            JSONObject body=new JSONObject().put("filename",name).put("size",size).put("chunk_size",chunkSize).put("scope",project>0?"project":"personal")
                .put("parent_id",parent).put("mime_type",mime==null?"application/octet-stream":mime);
            if(project>0)body.put("project_id",project);
            JSONObject session=json(c,"/api/files/upload-sessions","POST",body,account).getJSONObject("session");sessionId=session.getString("upload_id");
            chunkSize=session.getInt("chunk_size");long sent=0;int index=0;
            try(InputStream input=local==null?c.getContentResolver().openInputStream(uri):new FileInputStream(local)) {
                if(input==null)throw new IOException("无法读取所选文件");
                while(sent<size){int bytes=(int)Math.min(chunkSize,size-sent);byte[] chunk=new byte[bytes];int read=0;while(read<bytes){int n=input.read(chunk,read,bytes-read);if(n<0)throw new IOException("文件在上传期间变更，请重试");read+=n;}
                    putChunk(c,sessionId,index++,chunk,account);sent+=bytes;progress.update(name+" · "+(sent*100/size)+"%");}
                if(input.read()!=-1)throw new IOException("文件在上传期间变更，请重试");
            }
            JSONObject file=json(c,"/api/files/upload-sessions/"+sessionId+"/complete","POST",new JSONObject(),account).getJSONObject("file");complete=true;return file;
        } finally {
            if(local!=null)local.delete();
            if(sessionId!=null&&!complete)try{json(c,"/api/files/upload-sessions/"+sessionId,"DELETE",null,account);}catch(Exception ignored){}
        }
    }
    private static long length(Context c,Uri uri){if("file".equals(uri.getScheme()))return new File(uri.getPath()).length();try(Cursor cursor=c.getContentResolver().query(uri,new String[]{OpenableColumns.SIZE},null,null,null)){if(cursor!=null&&cursor.moveToFirst()&&!cursor.isNull(0))return cursor.getLong(0);}catch(Exception ignored){}return -1;}
    private static JSONObject emptyUpload(Context c,String name,String mime,long parent,long project,NetDiskSession.Account account)throws Exception {
        String boundary="dcp-"+UUID.randomUUID();ByteArrayOutputStream body=new ByteArrayOutputStream();
        Map<String,String> values=new LinkedHashMap<>();values.put("scope",project>0?"project":"personal");values.put("parent_id",""+parent);if(project>0)values.put("project_id",""+project);
        for(Map.Entry<String,String> value:values.entrySet())body.write(("--"+boundary+"\r\nContent-Disposition: form-data; name=\""+value.getKey()+"\"\r\n\r\n"+value.getValue()+"\r\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));
        String safe=name.replace("\"","_").replace("\r","_").replace("\n","_");
        body.write(("--"+boundary+"\r\nContent-Disposition: form-data; name=\"file\"; filename=\""+safe+"\"\r\nContent-Type: "+(mime==null?"application/octet-stream":mime)+"\r\n\r\n\r\n--"+boundary+"--\r\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));
        NetDiskSession.AuthorizedConnection opened=NetDiskSession.openBound(c,"/api/files/upload","POST",account);HttpURLConnection connection=opened.connection;
        try{connection.setDoOutput(true);connection.setRequestProperty("Content-Type","multipart/form-data; boundary="+boundary);connection.setFixedLengthStreamingMode(body.size());
            try(OutputStream output=connection.getOutputStream()){body.writeTo(output);}JSONObject result=NetDiskSession.read(connection);NetDiskSession.guard(c,account,()->{});return result.getJSONObject("file");
        }finally{connection.disconnect();}
    }
    private static void putChunk(Context c,String id,int index,byte[] bytes,NetDiskSession.Account account)throws Exception {
        for(int attempt=0;attempt<2;attempt++){
            NetDiskSession.AuthorizedConnection opened=NetDiskSession.openBound(c,"/api/files/upload-sessions/"+id+"/chunks/"+index,"PUT",account);HttpURLConnection connection=opened.connection;
            try{connection.setDoOutput(true);connection.setRequestProperty("Content-Type","application/octet-stream");connection.setFixedLengthStreamingMode(bytes.length);
                try(OutputStream output=connection.getOutputStream()){output.write(bytes);}
                if(connection.getResponseCode()==401&&attempt==0){NetDiskSession.ensure(c,true);NetDiskSession.guard(c,account,()->{});continue;}
                NetDiskSession.read(connection);NetDiskSession.guard(c,account,()->{});return;
            }finally{connection.disconnect();}
        }
    }
    static void download(Context c,long id,OutputStream output,NetDiskSession.Account account,Progress progress)throws Exception {
        for(int attempt=0;attempt<2;attempt++){
            NetDiskSession.AuthorizedConnection opened=NetDiskSession.openBound(c,"/api/files/"+id+"/download","GET",account);HttpURLConnection connection=opened.connection;
            try{int code=connection.getResponseCode();if(code==401&&attempt==0){NetDiskSession.ensure(c,true);NetDiskSession.guard(c,account,()->{});continue;}
                if(code<200||code>=300){NetDiskSession.read(connection);throw new IOException("下载失败 HTTP "+code);}
                long size=-1;try{size=Long.parseLong(connection.getHeaderField("Content-Length"));}catch(Exception ignored){}long received=0;byte[] buffer=new byte[65536];int n;
                try(InputStream input=connection.getInputStream()) {while((n=input.read(buffer))!=-1){NetDiskSession.guard(c,account,()->{});output.write(buffer,0,n);received+=n;if(received%(1024*1024)<65536)progress.update(size>0?"正在下载 · "+received*100/size+"%":"正在下载 · "+size(received));}}
                NetDiskSession.guard(c,account,()->{});output.flush();return;
            }finally{connection.disconnect();}
        }
    }
    static String size(long bytes){if(bytes<1024)return bytes+" B";if(bytes<1024*1024)return String.format(Locale.CHINA,"%.1f KB",bytes/1024d);if(bytes<1024L*1024*1024)return String.format(Locale.CHINA,"%.1f MB",bytes/(1024d*1024));return String.format(Locale.CHINA,"%.2f GB",bytes/(1024d*1024*1024));}
}
