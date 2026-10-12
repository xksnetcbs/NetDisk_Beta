package top.dcpstudios.calendarwidget;

import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.drawable.*;
import android.text.InputType;
import android.view.*;
import android.widget.*;

/** Compact visual controls with generous touch targets, instant feedback and system typography. */
final class NetDiskUi {
    final MainActivity a;
    NetDiskUi(MainActivity a){this.a=a;}
    TextView text(String value,int sp,int color,boolean bold){TextView t=new TextView(a);t.setText(value);t.setTextSize(sp);t.setTextColor(color);t.setFontFeatureSettings("kern");t.setTypeface(null,bold?Typeface.BOLD:Typeface.NORMAL);t.setLineSpacing(a.d(2),1);return t;}
    GradientDrawable shape(int color,int radius){GradientDrawable g=new GradientDrawable();g.setColor(color);g.setCornerRadius(a.d(radius));return g;}
    void feedback(View v,int color,int radius){v.setBackground(new RippleDrawable(ColorStateList.valueOf(a.dark?0x28ffffff:0x17007aff),shape(color,radius),null));}
    Button button(String label,String symbol,Runnable action){return button(label,symbol,action,false);}
    Button button(String label,String symbol,Runnable action,boolean primary){
        int primaryText=a.dark?0xff091f3b:0xffffffff;Button b=new Button(a);b.setText(label);b.setAllCaps(false);b.setTextSize(13);b.setTypeface(null,Typeface.BOLD);b.setTextColor(primary?primaryText:a.accent);b.setMinWidth(0);b.setMinimumWidth(0);b.setMinHeight(a.d(44));b.setMinimumHeight(a.d(44));b.setElevation(0);b.setStateListAnimator(null);b.setGravity(Gravity.CENTER);b.setPadding(a.d(12),0,a.d(12),0);
        int fill=primary?a.accent:a.dark?0xff252528:0xffe9eef5;Drawable face=shape(fill,10);b.setBackground(new RippleDrawable(ColorStateList.valueOf(primary?0x33ffffff:a.dark?0x25ffffff:0x20007aff),new InsetDrawable(face,0,a.d(6),0,a.d(6)),new InsetDrawable(shape(0xffffffff,10),0,a.d(6),0,a.d(6))));
        if(symbol!=null){Drawable icon=NetDiskIcons.drawable(symbol,primary?primaryText:a.accent,a.d(17));icon.setBounds(0,0,a.d(17),a.d(17));b.setCompoundDrawables(icon,null,null,null);b.setCompoundDrawablePadding(a.d(label.isEmpty()?0:5));}
        b.setContentDescription(label);b.setTag("netdisk-control");b.setOnClickListener(v->action.run());return b;
    }
    Button icon(String name,String description,Runnable action){Button b=button("",name,action);b.setContentDescription(description);b.setPadding(a.d(13),0,a.d(13),0);return b;}
    Button segment(String label,String symbol,boolean selected,Runnable action){Button b=button(label,symbol,action);int color=selected?a.surface:android.graphics.Color.TRANSPARENT;b.setTextColor(selected?a.ink:a.muted);b.setBackground(new RippleDrawable(ColorStateList.valueOf(a.dark?0x25ffffff:0x16000000),new InsetDrawable(shape(color,9),a.d(3),a.d(5),a.d(3),a.d(5)),null));Drawable icon=NetDiskIcons.drawable(symbol,selected?a.accent:a.muted,a.d(17));icon.setBounds(0,0,a.d(17),a.d(17));b.setCompoundDrawables(icon,null,null,null);b.setSelected(selected);return b;}
    EditText field(String hint,boolean secret){EditText input=new EditText(a);input.setSingleLine(true);input.setTextColor(a.ink);input.setHintTextColor(a.muted);input.setHint(hint);input.setTextSize(15);input.setPadding(a.d(14),a.d(10),a.d(14),a.d(10));input.setMinHeight(a.d(48));input.setBackground(shape(a.dark?0xff2b2b2e:0xfff2f3f7,11));input.setInputType(secret?InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD:InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_NORMAL);if(android.os.Build.VERSION.SDK_INT>=26)input.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);return input;}
    ImageView symbol(String name,int color,int size){ImageView icon=new ImageView(a);icon.setImageDrawable(NetDiskIcons.drawable(name,color,a.d(size)));icon.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);return icon;}
    LinearLayout surface(){LinearLayout card=a.column();card.setBackground(shape(a.surface,16));return card;}
}
