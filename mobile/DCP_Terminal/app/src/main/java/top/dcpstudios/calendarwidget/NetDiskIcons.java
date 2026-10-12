package top.dcpstudios.calendarwidget;

import android.graphics.*;
import android.graphics.drawable.Drawable;
import org.json.JSONObject;
import java.util.Locale;

/** Original, consistent 24-unit outline symbols; no font glyph or platform icon fallback. */
final class NetDiskIcons {
    static String file(JSONObject node) {
        if("folder".equals(node.optString("type")))return "folder";
        String mime=node.optString("mime_type").toLowerCase(Locale.ROOT),name=node.optString("name").toLowerCase(Locale.ROOT);
        if(mime.startsWith("image/")||name.matches(".*\\.(png|jpg|jpeg|gif|webp|heic|svg)$"))return "image";
        if(mime.startsWith("video/")||name.matches(".*\\.(mp4|mov|mkv|webm)$"))return "video";
        if(mime.startsWith("audio/")||name.matches(".*\\.(mp3|m4a|wav|flac|ogg)$"))return "audio";
        if(name.matches(".*\\.(zip|rar|7z|tar|gz)$"))return "archive";
        if(name.endsWith(".pdf"))return "pdf";
        return "document";
    }
    static Drawable drawable(String name,int color,int pixels){return new Symbol(name,color,pixels);}
    static final class Symbol extends Drawable {
        final String name;final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);final int size;
        Symbol(String name,int color,int size){this.name=name;this.size=size;paint.setColor(color);paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(1.65f);paint.setStrokeCap(Paint.Cap.ROUND);paint.setStrokeJoin(Paint.Join.ROUND);}
        private void lines(Canvas c,float...xy){Path p=new Path();p.moveTo(xy[0],xy[1]);for(int i=2;i<xy.length;i+=2)p.lineTo(xy[i],xy[i+1]);c.drawPath(p,paint);}
        private void box(Canvas c,float x,float y,float w,float h,float radius){c.drawRoundRect(x,y,x+w,y+h,radius,radius,paint);}
        private void dot(Canvas c,float x,float y){Paint.Style old=paint.getStyle();paint.setStyle(Paint.Style.FILL);c.drawCircle(x,y,1.1f,paint);paint.setStyle(old);}
        private void page(Canvas c){lines(c,14,3,6,3,6,21,18,21,18,7,14,3,14,7,18,7);}
        @Override public void draw(Canvas canvas){Rect b=getBounds();canvas.save();canvas.translate(b.left,b.top);canvas.scale(b.width()/24f,b.height()/24f);
            switch(name){
                case "folder":lines(canvas,3,8,3,5,9,5,11,8,21,8,21,19,3,19,3,8,21,8);break;
                case "projects":box(canvas,3,6,18,15,2);lines(canvas,8,6,8,3,16,3,16,6);lines(canvas,3,11,21,11);break;
                case "personal":canvas.drawCircle(12,7,3,paint);Path p=new Path();p.moveTo(5,21);p.lineTo(5,18);p.cubicTo(5,11,19,11,19,18);p.lineTo(19,21);canvas.drawPath(p,paint);break;
                case "search":canvas.drawCircle(10,10,6,paint);lines(canvas,15,15,21,21);break;
                case "refresh":Path refresh=new Path();refresh.addArc(4,4,20,20,45,285);canvas.drawPath(refresh,paint);lines(canvas,20,4,20,10,14,10);break;
                case "plus":lines(canvas,12,5,12,19);lines(canvas,5,12,19,12);break;
                case "upload":lines(canvas,12,17,12,3);lines(canvas,7,8,12,3,17,8);lines(canvas,4,15,4,21,20,21,20,15);break;
                case "download":lines(canvas,12,3,12,17);lines(canvas,7,12,12,17,17,12);lines(canvas,4,17,4,21,20,21,20,17);break;
                case "back":lines(canvas,14,5,7,12,14,19);break;
                case "chevron":lines(canvas,9,6,15,12,9,18);break;
                case "more":dot(canvas,5,12);dot(canvas,12,12);dot(canvas,19,12);break;
                case "account":canvas.drawCircle(12,12,9,paint);canvas.drawCircle(12,9,3,paint);Path a=new Path();a.moveTo(5.5f,18);a.cubicTo(6,12,18,12,18.5f,18);canvas.drawPath(a,paint);break;
                case "link":Path l=new Path();l.addArc(3,10,13,20,45,270);l.addArc(11,4,21,14,225,270);canvas.drawPath(l,paint);lines(canvas,8,16,16,8);break;
                case "image":box(canvas,3,3,18,18,2);canvas.drawCircle(8,8,1.5f,paint);lines(canvas,3,18,9,12,13,16,16,11,21,17);break;
                case "video":box(canvas,3,5,18,14,2);lines(canvas,10,9,16,12,10,15,10,9);break;
                case "audio":lines(canvas,10,16,10,5,20,3,20,14);canvas.drawOval(4,15,10,20,paint);canvas.drawOval(14,13,20,18,paint);break;
                case "archive":box(canvas,4,3,16,18,2);lines(canvas,10,3,10,6,14,6,14,9,10,9,10,12,14,12,14,15);box(canvas,10,16,4,3,1);break;
                case "pdf":page(canvas);lines(canvas,9,17,11,10,14,17);lines(canvas,10,14,13,14);break;
                case "document":page(canvas);lines(canvas,9,12,15,12);lines(canvas,9,16,15,16);break;
                case "eye":Path e=new Path();e.moveTo(2,12);e.cubicTo(8,3,16,3,22,12);e.cubicTo(16,21,8,21,2,12);canvas.drawPath(e,paint);canvas.drawCircle(12,12,3,paint);break;
                case "external":lines(canvas,14,3,21,3,21,10);lines(canvas,21,3,10,14);lines(canvas,10,5,4,5,4,21,19,21,19,14);break;
                case "info":canvas.drawCircle(12,12,9,paint);dot(canvas,12,7);lines(canvas,12,11,12,17);break;
                case "edit":lines(canvas,4,20,5,14,17,2,22,7,10,19,4,20);lines(canvas,14,5,19,10);break;
                case "move":lines(canvas,12,2,12,22);lines(canvas,2,12,22,12);lines(canvas,8,6,12,2,16,6);lines(canvas,8,18,12,22,16,18);lines(canvas,6,8,2,12,6,16);lines(canvas,18,8,22,12,18,16);break;
                case "trash":lines(canvas,3,6,21,6);lines(canvas,8,6,8,3,16,3,16,6);lines(canvas,5,6,6,21,18,21,19,6);lines(canvas,10,10,10,17);lines(canvas,14,10,14,17);break;
                default:page(canvas);
            }
            canvas.restore();
        }
        @Override public int getIntrinsicWidth(){return size;}@Override public int getIntrinsicHeight(){return size;}
        @Override public void setAlpha(int alpha){paint.setAlpha(alpha);invalidateSelf();}
        @Override public void setColorFilter(ColorFilter filter){paint.setColorFilter(filter);invalidateSelf();}
        @Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }
}
