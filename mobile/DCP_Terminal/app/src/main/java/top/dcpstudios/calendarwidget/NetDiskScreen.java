package top.dcpstudios.calendarwidget;

import android.app.*;
import android.content.*;
import android.graphics.drawable.*;
import android.net.Uri;
import android.text.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.util.*;

/** Native file browser; supported files open in a separate preview surface. */
final class NetDiskScreen {
    private final MainActivity activity;
    private final NetDiskUi ui;
    private final List<AlertDialog> dialogs=new ArrayList<>();
    private final List<JSONObject> folders=new ArrayList<>();
    private List<JSONObject> items=new ArrayList<>();
    private LinearLayout content;private TextView status;private ListView list;private EditText search;
    private String section="projects",query="",projectName="";
    private long projectId,viewEpoch,userId;
    private boolean busy,restoring;
    private JSONObject pendingDownload;
    private NetDiskSession.Account pendingAccount;
    private long uploadParent,uploadProject;
    EditText username,password;
    Button loginButton;

    NetDiskScreen(MainActivity activity){this.activity=activity;ui=new NetDiskUi(activity);}
    void show(){
        activity.base("netdisk");viewEpoch++;
        long next=NetDiskSession.prefs(activity).getLong("user_id",0);
        if(next!=userId){userId=next;folders.clear();items.clear();section="projects";query="";}
        header();content=activity.column();activity.root.addView(content,new LinearLayout.LayoutParams(-1,0,1));
        if(NetDiskSession.isLoggedIn(activity)){browser();reload();}else login();
        activity.navigation("netdisk");
    }
    private void header(){
        LinearLayout row=new LinearLayout(activity);row.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout words=activity.column();TextView caption=ui.text("DCP FILES",10,activity.muted,true);caption.setLetterSpacing(.1f);words.addView(caption);words.addView(ui.text("网盘",27,activity.ink,true));row.addView(words,new LinearLayout.LayoutParams(0,-2,1));
        row.addView(ui.icon(NetDiskSession.isLoggedIn(activity)?"account":"link",NetDiskSession.isLoggedIn(activity)?"账号":"站点",()->{if(NetDiskSession.isLoggedIn(activity))accountMenu();else connectionSettings();}),new LinearLayout.LayoutParams(activity.d(48),activity.d(48)));
        activity.root.addView(row);activity.space(activity.root,12);
    }
    private void login(){
        ScrollView scroll=new ScrollView(activity);scroll.setFillViewport(true);LinearLayout box=activity.column();box.setPadding(0,activity.d(24),0,activity.d(24));scroll.addView(box);content.addView(scroll,new LinearLayout.LayoutParams(-1,-1));
        box.addView(ui.text("登录网盘",23,activity.ink,true));activity.space(box,7);
        box.addView(ui.text("在这台设备上自动恢复登录",13,activity.muted,false));activity.space(box,20);
        LinearLayout form=ui.surface();form.setPadding(activity.d(16),activity.d(16),activity.d(16),activity.d(14));box.addView(form);
        username=field("用户名",false);password=field("密码",true);form.addView(username);activity.space(form,10);form.addView(password);activity.space(form,10);
        status=ui.text("",12,activity.muted,false);status.setMinHeight(activity.d(20));form.addView(status);
        loginButton=ui.button("登录",null,this::submitLogin,true);form.addView(loginButton,new LinearLayout.LayoutParams(-1,activity.d(48)));activity.space(box,12);
        TextView origin=ui.text(NetDiskSession.base(activity),11,activity.muted,false);origin.setGravity(Gravity.CENTER);box.addView(origin);
        if(!NetDiskSession.prefs(activity).getBoolean("signed_out",false)&&!NetDiskSession.cookie(activity).isEmpty()&&!restoring){
            restoring=true;status.setText("正在恢复设备登录…");long epoch=viewEpoch;
            TerminalClient.IO.execute(()->{Exception failure=null;try{NetDiskSession.ensure(activity,true);TerminalClient.sync(activity,false);}catch(Exception e){failure=e;}
                final Exception error=failure;activity.runOnUiThread(()->{restoring=false;if(!visible(epoch))return;if(error==null)show();else status.setText("登录会话已失效，请重新登录");});});
        }
    }
    private EditText field(String hint,boolean secret){return ui.field(hint,secret);}
    private AlertDialog showDialog(AlertDialog dialog){dialogs.add(dialog);dialog.setOnDismissListener(d->dialogs.remove(dialog));dialog.show();for(int id:new int[]{AlertDialog.BUTTON_POSITIVE,AlertDialog.BUTTON_NEGATIVE,AlertDialog.BUTTON_NEUTRAL}){Button button=dialog.getButton(id);if(button!=null){button.setAllCaps(false);button.setTextSize(13);button.setMinHeight(activity.d(44));}}return dialog;}
    private void bound(NetDiskSession.Account account,Runnable action){try{NetDiskSession.guard(activity,account,()->action.run());}catch(NetDiskSession.AccountChanged ignored){}catch(Exception e){activity.error(e);}}
    void submitLogin(){
        if(busy||username==null||password==null)return;String name=username.getText().toString().trim(),secret=password.getText().toString();
        if(name.isEmpty()||secret.isEmpty()){status.setText("请输入用户名和密码");return;}
        password.setText("");busy=true;loginButton.setEnabled(false);status.setText("正在登录…");long epoch=viewEpoch;
        ((android.view.inputmethod.InputMethodManager)activity.getSystemService(Context.INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(password.getWindowToken(),0);
        TerminalClient.IO.execute(()->{Exception failure=null;try{NetDiskSession.login(activity,name,secret);TerminalClient.sync(activity,false);}catch(Exception e){failure=e;}
            final Exception error=failure;activity.runOnUiThread(()->{busy=false;if(!visible(epoch))return;if(error==null){userId=NetDiskSession.prefs(activity).getLong("user_id",0);folders.clear();show();}else{loginButton.setEnabled(true);status.setText(error.getMessage());}});});
    }
    private void accountMenu(){showDialog(new AlertDialog.Builder(activity).setTitle(NetDiskSession.userName(activity)).setItems(new String[]{"切换站点","退出登录"},(dialog,index)->{if(index==0)connectionSettings();else logout();}).setNegativeButton("取消",null).create());}
    void logout(){
        // Clear the local account immediately; server revocation does not block UI.
        final String cookies=NetDiskSession.cookie(activity),origin=NetDiskSession.base(activity);
        NetDiskSession.observeWebLogin(activity,true);android.webkit.CookieManager.getInstance().setCookie(origin+"/api/auth/refresh","dcp_netdisk_session=; Path=/api/auth; Secure; HttpOnly; Max-Age=0");android.webkit.CookieManager.getInstance().flush();
        folders.clear();items.clear();userId=0;show();activity.events=CalendarStore.read(activity);CalendarWidget.renderAll(activity);
        TerminalClient.IO.execute(()->{try{NetDiskSession.revoke(origin,cookies);}catch(Exception ignored){}});
    }
    private void browser(){
        LinearLayout tabs=new LinearLayout(activity);tabs.setBackground(ui.shape(activity.dark?0xff252528:0xffe5e7ed,12));tabs.addView(ui.segment("项目","projects","projects".equals(section),()->{section="projects";folders.clear();items.clear();query="";show();}),new LinearLayout.LayoutParams(0,activity.d(44),1));
        tabs.addView(ui.segment("个人文件","personal","personal".equals(section),()->{section="personal";folders.clear();items.clear();query="";show();}),new LinearLayout.LayoutParams(0,activity.d(44),1));content.addView(tabs);activity.space(content,10);
        LinearLayout path=new LinearLayout(activity);path.setGravity(Gravity.CENTER_VERTICAL);
        if(!folders.isEmpty())path.addView(ui.icon("back","返回上一级",()->{if(folders.size()>1){folders.remove(folders.size()-1);show();}else{folders.clear();items.clear();show();}}),new LinearLayout.LayoutParams(activity.d(48),activity.d(48)));
        TextView label=ui.text(folders.isEmpty()?("personal".equals(section)?"个人文件":"我的项目"):breadcrumb(),13,activity.muted,false);label.setMaxLines(2);label.setPadding(activity.d(6),0,activity.d(6),0);path.addView(label,new LinearLayout.LayoutParams(0,-2,1));
        path.addView(ui.icon("refresh","刷新",this::reload),new LinearLayout.LayoutParams(activity.d(48),activity.d(48)));content.addView(path);
        LinearLayout tools=new LinearLayout(activity);
        if(!folders.isEmpty()){
            tools.addView(ui.button("上传文件","upload",this::chooseUpload),new LinearLayout.LayoutParams(0,activity.d(44),1));
            LinearLayout.LayoutParams second=new LinearLayout.LayoutParams(0,activity.d(44),1);second.leftMargin=activity.d(8);
            tools.addView(ui.button("新建文件夹","plus",()->{final long target=parent(),project=projectId;prompt("新建文件夹","",name->mutate("正在创建…",a->NetDiskFiles.createFolder(activity,target,project,name,a)));}),second);
        }else if("projects".equals(section))tools.addView(ui.button("新建项目","plus",this::newProject),new LinearLayout.LayoutParams(-1,activity.d(44)));
        content.addView(tools);activity.space(content,8);
        search=field("搜索当前列表",false);Drawable searchIcon=NetDiskIcons.drawable("search",activity.muted,activity.d(18));searchIcon.setBounds(0,0,activity.d(18),activity.d(18));search.setCompoundDrawables(searchIcon,null,null,null);search.setCompoundDrawablePadding(activity.d(8));search.setText(query);content.addView(search,new LinearLayout.LayoutParams(-1,activity.d(48)));
        search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int start,int count,int after){}public void onTextChanged(CharSequence s,int start,int before,int count){query=s.toString();renderItems();}public void afterTextChanged(Editable s){}});
        status=ui.text("",11,activity.muted,false);status.setPadding(activity.d(6),activity.d(10),activity.d(6),activity.d(10));content.addView(status);
        list=new ListView(activity);list.setDivider(new ColorDrawable(activity.line));list.setDividerHeight(activity.d(.5f));list.setSelector(new ColorDrawable(android.graphics.Color.TRANSPARENT));list.setBackground(ui.shape(activity.surface,16));list.setClipToOutline(true);list.setClipToPadding(false);content.addView(list,new LinearLayout.LayoutParams(-1,0,1));renderItems();
    }
    private String breadcrumb(){StringBuilder text=new StringBuilder(projectId>0?projectName:"个人文件");for(int i=1;i<folders.size();i++)text.append(" / ").append(folders.get(i).optString("name"));return text.toString();}
    private long parent(){return folders.isEmpty()?0:folders.get(folders.size()-1).optLong("id");}
    private boolean visible(long epoch){return !activity.isDestroyed()&&"netdisk".equals(activity.page)&&epoch==viewEpoch;}
    void reload(){
        if(!NetDiskSession.isLoggedIn(activity))return;final long epoch=++viewEpoch;final String currentSection=section;final long currentParent=parent();status.setText("正在加载…");
        TerminalClient.IO.execute(()->{try{
            NetDiskSession.Account account=NetDiskSession.account(activity);List<JSONObject> loaded;JSONObject root=null;
            if("projects".equals(currentSection)&&currentParent==0)loaded=NetDiskFiles.projects(activity,account);
            else{long folder=currentParent;if(folder==0){root=NetDiskFiles.root(activity,0,account);folder=root.getLong("id");}loaded=NetDiskFiles.list(activity,folder,account);}
            final JSONObject nextRoot=root;NetDiskSession.ui(activity,account,()->{if(!visible(epoch))return;if(nextRoot!=null){projectId=0;folders.add(nextRoot);items=loaded;show();return;}items=loaded;renderItems();});
        }catch(NetDiskSession.AccountChanged ignored){}catch(Exception e){activity.runOnUiThread(()->{if(visible(epoch)){status.setText(e.getMessage()+" · 点击刷新重试");if(!NetDiskSession.isLoggedIn(activity))show();}});}});
    }
    private void renderItems(){
        if(list==null||status==null)return;List<JSONObject> shown=new ArrayList<>();for(JSONObject item:items)if(item.optString("name").toLowerCase(Locale.ROOT).contains(query.toLowerCase(Locale.ROOT)))shown.add(item);
        boolean projects="projects".equals(section)&&folders.isEmpty();status.setText(shown.size()+(projects?" 个项目":" 项")+(query.isEmpty()?"":" · 搜索结果"));
        list.setAdapter(new BaseAdapter(){public int getCount(){return shown.size();}public Object getItem(int index){return shown.get(index);}public long getItemId(int index){return shown.get(index).optLong("id");}
            public View getView(int index,View recycled,ViewGroup owner){JSONObject item=shown.get(index);LinearLayout row=new LinearLayout(activity);row.setGravity(Gravity.CENTER_VERTICAL);row.setPadding(activity.d(12),activity.d(8),activity.d(6),activity.d(8));row.setMinimumHeight(activity.d(64));ui.feedback(row,activity.surface,0);
                boolean folder="folder".equals(item.optString("type"));String symbol=projects?"projects":NetDiskIcons.file(item);int tone=projects||folder?activity.accent:"image".equals(symbol)?(activity.dark?0xff79cda0:0xff258450):"pdf".equals(symbol)?(activity.dark?0xfff3a49d:0xffc4544c):activity.muted;
                ImageView icon=ui.symbol(symbol,tone,22);icon.setPadding(activity.d(7),activity.d(7),activity.d(7),activity.d(7));icon.setBackground(ui.shape(activity.dark?0xff2b2b2e:0xfff1f4f9,10));LinearLayout.LayoutParams ip=new LinearLayout.LayoutParams(activity.d(36),activity.d(36));ip.rightMargin=activity.d(11);row.addView(icon,ip);
                LinearLayout words=activity.column();TextView name=ui.text(item.optString("name"),14,activity.ink,true);name.setMaxLines(2);name.setEllipsize(TextUtils.TruncateAt.END);words.addView(name);
                String subtitle=projects?(item.optString("key")+" · "+role(item.optString("role"))):folder?"文件夹":NetDiskFiles.size(item.optLong("size_bytes"));words.addView(ui.text(subtitle,11,activity.muted,false));row.addView(words,new LinearLayout.LayoutParams(0,-2,1));
                if(projects||folder){ImageView next=ui.symbol("chevron",activity.muted,14);row.addView(next,new LinearLayout.LayoutParams(activity.d(24),activity.d(24)));}
                Button menu=ui.icon("more",item.optString("name")+(projects?" 项目操作":" 文件操作"),()->{if(projects)projectDetails(item);else fileActions(item);});
                // Focusable children suppress ListView's row click and long-click.
                // Keep the separate menu touch action without taking item focus.
                menu.setFocusable(false);menu.setFocusableInTouchMode(false);
                row.addView(menu,new LinearLayout.LayoutParams(activity.d(48),activity.d(48)));return row;}});
        list.setOnItemClickListener((p,v,index,id)->{JSONObject item=shown.get(index);if(projects)openProject(item);else if("folder".equals(item.optString("type"))){folders.add(item);items.clear();show();}else NetDiskPreview.open(activity,item);});
        list.setOnItemLongClickListener((p,v,index,id)->{if(!projects)fileActions(shown.get(index));else projectDetails(shown.get(index));return true;});
        if(shown.isEmpty())status.setText(query.isEmpty()?(projects?"还没有项目，可新建项目或打开个人文件":"文件夹为空，可上传文件或新建文件夹"):"没有找到匹配结果");
    }
    private static String role(String value){return "creator".equals(value)?"创建者":"admin".equals(value)?"管理员":"guest".equals(value)?"访客":"成员";}
    void openProject(JSONObject project){
        long epoch=++viewEpoch;status.setText("正在打开项目…");TerminalClient.IO.execute(()->{try{NetDiskSession.Account account=NetDiskSession.account(activity);JSONObject root=NetDiskFiles.root(activity,project.getLong("id"),account);
            NetDiskSession.ui(activity,account,()->{if(!visible(epoch))return;projectId=project.getLong("id");projectName=project.optString("name");folders.clear();folders.add(root);items.clear();show();});
        }catch(NetDiskSession.AccountChanged ignored){}catch(Exception e){activity.runOnUiThread(()->{if(visible(epoch)){activity.error(e);reload();}});}});
    }
    private void projectDetails(JSONObject project){try{final NetDiskSession.Account account=NetDiskSession.account(activity);showDialog(new AlertDialog.Builder(activity).setTitle(project.optString("name")).setMessage("项目 Key："+project.optString("key")+"\n我的角色："+role(project.optString("role"))+"\n\n"+project.optString("description","")).setPositiveButton("打开文件",(d,i)->bound(account,()->openProject(project))).setNegativeButton("关闭",null).create());}catch(Exception e){activity.error(e);}}
    private void newProject(){
        final NetDiskSession.Account account;try{account=NetDiskSession.account(activity);}catch(Exception e){activity.error(e);return;}
        LinearLayout box=activity.column();box.setPadding(activity.d(20),activity.d(8),activity.d(20),0);EditText name=field("项目名称",false),key=field("项目 Key（唯一）",false);box.addView(name);activity.space(box,10);box.addView(key);
        AlertDialog dialog=new AlertDialog.Builder(activity).setTitle("新建项目").setView(box).setNegativeButton("取消",null).setPositiveButton("创建",null).create();dialog.setOnShowListener(d->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{if(name.getText().toString().trim().isEmpty()||key.getText().toString().trim().isEmpty()){Toast.makeText(activity,"请输入项目名称和 Key",Toast.LENGTH_SHORT).show();return;}
            dialog.dismiss();bound(account,()->mutate("正在创建项目…",a->NetDiskFiles.json(activity,"/api/projects","POST",new JSONObject().put("name",name.getText().toString().trim()).put("key",key.getText().toString().trim()),a)));}));showDialog(dialog);
    }
    interface Named { void run(String name); }
    private void prompt(String title,String value,Named action){final NetDiskSession.Account account;try{account=NetDiskSession.account(activity);}catch(Exception e){activity.error(e);return;}EditText input=field("名称",false);input.setText(value);input.setSelection(input.length());LinearLayout box=activity.column();box.setPadding(activity.d(20),activity.d(6),activity.d(20),0);box.addView(input);
        AlertDialog dialog=new AlertDialog.Builder(activity).setTitle(title).setView(box).setNegativeButton("取消",null).setPositiveButton("保存",null).create();dialog.setOnShowListener(d->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{String name=input.getText().toString().trim();if(name.isEmpty()){input.setError("请输入名称");return;}dialog.dismiss();bound(account,()->action.run(name));}));showDialog(dialog);}
    private void fileActions(JSONObject item){boolean folder="folder".equals(item.optString("type"));String[] labels=folder?new String[]{"详细信息","重命名","移动","删除"}:new String[]{"预览","下载 / 保存到设备","打开文件","详细信息","重命名","移动","删除"};
        String[] icons=folder?new String[]{"info","edit","move","trash"}:new String[]{"eye","download","external","info","edit","move","trash"};
        final NetDiskSession.Account account;try{account=NetDiskSession.account(activity);}catch(Exception e){activity.error(e);return;}
        LinearLayout box=activity.column();box.setPadding(activity.d(12),0,activity.d(12),activity.d(4));AlertDialog dialog=new AlertDialog.Builder(activity).setTitle(item.optString("name")).setView(box).setNegativeButton("关闭",null).create();
        for(int i=0;i<labels.length;i++){final String action=labels[i];LinearLayout row=new LinearLayout(activity);row.setGravity(Gravity.CENTER_VERTICAL);row.setMinimumHeight(activity.d(48));row.setPadding(activity.d(12),0,activity.d(12),0);ui.feedback(row,activity.surface,10);int color="删除".equals(action)?activity.dark?0xffff8d83:0xffd43832:activity.accent;row.addView(ui.symbol(icons[i],color,20),new LinearLayout.LayoutParams(activity.d(24),activity.d(24)));TextView text=ui.text(action,14,"删除".equals(action)?color:activity.ink,false);text.setPadding(activity.d(12),0,0,0);row.addView(text);row.setContentDescription(action);row.setOnClickListener(v->{dialog.dismiss();bound(account,()->{if("预览".equals(action))NetDiskPreview.open(activity,item);else if(action.startsWith("下载"))chooseDownload(item);else if("打开文件".equals(action))openFile(item);else if("详细信息".equals(action))details(item);else if("重命名".equals(action))prompt("重命名",item.optString("name"),name->bound(account,()->mutate("正在重命名…",a->NetDiskFiles.json(activity,"/api/files/"+item.getLong("id"),"PATCH",new JSONObject().put("name",name),a))));else if("移动".equals(action))move(item);else remove(item);});});box.addView(row,new LinearLayout.LayoutParams(-1,activity.d(48)));}
        showDialog(dialog);
    }
    private void details(JSONObject item){String text="类型："+("folder".equals(item.optString("type"))?"文件夹":item.optString("mime_type","文件"))+"\n大小："+NetDiskFiles.size(item.optLong("size_bytes"))+"\n修改："+item.optString("updated_at","—")+"\n创建："+item.optString("created_at","—")+"\n位置："+breadcrumb();showDialog(new AlertDialog.Builder(activity).setTitle(item.optString("name")).setMessage(text).setPositiveButton("关闭",null).create());}
    private void remove(JSONObject item){try{final NetDiskSession.Account account=NetDiskSession.account(activity);showDialog(new AlertDialog.Builder(activity).setTitle("删除“"+item.optString("name")+"”？").setMessage("folder".equals(item.optString("type"))?"文件夹内的文件也会被删除。":"文件将从网盘中删除。").setNegativeButton("取消",null).setPositiveButton("删除",(d,i)->bound(account,()->mutate("正在删除…",a->NetDiskFiles.json(activity,"/api/files/"+item.getLong("id"),"DELETE",null,a)))).create());}catch(Exception e){activity.error(e);}}
    private void move(JSONObject item){try{new MovePicker(item,NetDiskSession.account(activity)).show();}catch(Exception e){activity.error(e);}}
    private final class MovePicker {
        final JSONObject item;final NetDiskSession.Account account;final List<JSONObject> path=new ArrayList<>();AlertDialog dialog;ListView choices;TextView label;long load;
        MovePicker(JSONObject item,NetDiskSession.Account account){this.item=item;this.account=account;path.add(folders.get(0));}
        void show(){LinearLayout box=activity.column();box.setPadding(activity.d(16),0,activity.d(16),0);label=ui.text("",13,activity.muted,false);box.addView(label);box.addView(ui.button("上一级","back",()->{if(path.size()>1){path.remove(path.size()-1);reload();}}),new LinearLayout.LayoutParams(-1,activity.d(44)));choices=new ListView(activity);box.addView(choices,new LinearLayout.LayoutParams(-1,activity.d(280)));
            dialog=new AlertDialog.Builder(activity).setTitle("移动到…").setView(box).setNegativeButton("取消",null).setPositiveButton("移动到此文件夹",(d,i)->bound(account,()->mutate("正在移动…",a->NetDiskFiles.json(activity,"/api/files/"+item.getLong("id"),"PATCH",new JSONObject().put("parent_id",path.get(path.size()-1).getLong("id")),a)))).create();showDialog(dialog);reload();}
        void reload(){long epoch=++load;label.setText("正在加载…");long parent=path.get(path.size()-1).optLong("id");TerminalClient.IO.execute(()->{try{List<JSONObject> all=NetDiskFiles.list(activity,parent,account);List<JSONObject> dirs=new ArrayList<>();for(JSONObject row:all)if("folder".equals(row.optString("type"))&&row.optLong("id")!=item.optLong("id"))dirs.add(row);
                NetDiskSession.ui(activity,account,()->{if(!dialog.isShowing()||epoch!=load)return;label.setText(path.get(path.size()-1).optString("name")+" · "+dirs.size()+" 个文件夹");choices.setAdapter(new BaseAdapter(){public int getCount(){return dirs.size();}public Object getItem(int i){return dirs.get(i);}public long getItemId(int i){return dirs.get(i).optLong("id");}public View getView(int i,View old,ViewGroup parent){TextView row=ui.text(dirs.get(i).optString("name"),14,activity.ink,false);row.setPadding(activity.d(12),activity.d(12),activity.d(12),activity.d(12));row.setMinHeight(activity.d(48));Drawable icon=NetDiskIcons.drawable("folder",activity.accent,activity.d(20));icon.setBounds(0,0,activity.d(20),activity.d(20));row.setCompoundDrawables(icon,null,null,null);row.setCompoundDrawablePadding(activity.d(10));return row;}});choices.setOnItemClickListener((p,v,index,id)->{path.add(dirs.get(index));reload();});});
            }catch(Exception e){activity.runOnUiThread(()->bound(account,()->{if(dialog.isShowing()&&epoch==load)label.setText(e.getMessage());}));}});}
    }
    interface Mutation { Object run(NetDiskSession.Account account)throws Exception; }
    private void mutate(String message,Mutation work){if(busy)return;busy=true;status.setText(message);long epoch=viewEpoch;NetDiskSession.Account account;
        try{account=NetDiskSession.account(activity);}catch(Exception e){busy=false;activity.error(e);return;}
        TerminalClient.IO.execute(()->{Exception failure=null;try{work.run(account);}catch(Exception e){failure=e;}final Exception error=failure;
            activity.runOnUiThread(()->{busy=false;try{NetDiskSession.guard(activity,account,()->{if(!visible(epoch))return;if(error==null){Toast.makeText(activity,"操作完成",Toast.LENGTH_SHORT).show();reload();}else{status.setText(error.getMessage());activity.error(error);}});}catch(Exception ignored){}});});
    }
    private void chooseUpload(){if(busy||folders.isEmpty())return;try{pendingAccount=NetDiskSession.account(activity);uploadParent=parent();uploadProject=projectId;Intent pick=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*").putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true);activity.startActivityForResult(pick,43);}catch(Exception e){activity.error(e);}}
    boolean handleUpload(int result,Intent data){if(result!=Activity.RESULT_OK||data==null||pendingAccount==null)return true;List<Uri> uris=new ArrayList<>();if(data.getClipData()!=null){for(int i=0;i<data.getClipData().getItemCount();i++)uris.add(data.getClipData().getItemAt(i).getUri());}else if(data.getData()!=null)uris.add(data.getData());
        final NetDiskSession.Account account=pendingAccount;pendingAccount=null;final long parent=uploadParent,project=uploadProject,epoch=viewEpoch;busy=true;
        TerminalClient.IO.execute(()->{Exception failure=null;try{for(Uri uri:uris)NetDiskFiles.upload(activity,uri,parent,project,account,text->progress(text,account,epoch));}catch(Exception e){failure=e;}final Exception error=failure;activity.runOnUiThread(()->{busy=false;try{NetDiskSession.guard(activity,account,()->{if(error!=null)activity.error(error);if("netdisk".equals(activity.page))reload();Toast.makeText(activity,error==null?"上传完成":"上传未完成，请重试",Toast.LENGTH_LONG).show();});}catch(Exception ignored){}});});return true;
    }
    void chooseDownload(JSONObject item){try{pendingDownload=item;pendingAccount=NetDiskSession.account(activity);Intent save=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(item.optString("mime_type","application/octet-stream")).putExtra(Intent.EXTRA_TITLE,item.optString("name"));activity.startActivityForResult(save,44);}catch(Exception e){pendingDownload=null;pendingAccount=null;activity.error(e);}}
    void handleDownload(int result,Intent data){final JSONObject item=pendingDownload;final NetDiskSession.Account account=pendingAccount;pendingDownload=null;pendingAccount=null;if(result!=Activity.RESULT_OK||data==null||data.getData()==null||item==null||account==null)return;Uri uri=data.getData();
        final long epoch=viewEpoch;TerminalClient.IO.execute(()->{try(OutputStream output=activity.getContentResolver().openOutputStream(uri,"wt")){if(output==null)throw new IOException("无法保存到此位置");NetDiskFiles.download(activity,item.getLong("id"),output,account,text->progress(text,account,epoch));NetDiskSession.ui(activity,account,()->{Toast.makeText(activity,"文件已保存",Toast.LENGTH_LONG).show();reload();});}catch(Exception e){activity.runOnUiThread(()->bound(account,()->{if(visible(epoch))activity.error(e);}));}});
    }
    void openFile(JSONObject item){try{NetDiskSession.Account account=NetDiskSession.account(activity);final long epoch=viewEpoch;progress("正在下载以打开…",account,epoch);TerminalClient.IO.execute(()->{File local=null;try{File directory=new File(activity.getCacheDir(),"opened");directory.mkdirs();String name=item.optString("name","file").replaceAll("[\\\\/\\r\\n]","_");local=new File(directory,item.getLong("id")+"-"+name);
                try(OutputStream output=new FileOutputStream(local)){NetDiskFiles.download(activity,item.getLong("id"),output,account,text->progress(text,account,epoch));}final File file=local;
                NetDiskSession.ui(activity,account,()->{Uri uri=androidx.core.content.FileProvider.getUriForFile(activity,activity.getPackageName()+".files",file);Intent open=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,item.optString("mime_type","application/octet-stream")).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);try{activity.startActivity(Intent.createChooser(open,"打开文件"));}catch(Exception e){activity.error(e);}reload();});
            }catch(Exception e){if(local!=null)local.delete();activity.runOnUiThread(()->bound(account,()->{if(visible(epoch))activity.error(e);}));}});}catch(Exception e){activity.error(e);}}
    private void progress(String text,NetDiskSession.Account account,long epoch){activity.runOnUiThread(()->bound(account,()->{if(status!=null&&visible(epoch))status.setText(text);}));}
    void connectionSettings(){EditText input=field("HTTPS 站点",false);input.setText(NetDiskSession.base(activity));LinearLayout box=activity.column();box.setPadding(activity.d(20),0,activity.d(20),0);box.addView(input);
        showDialog(new AlertDialog.Builder(activity).setTitle("网盘站点").setView(box).setNegativeButton("取消",null).setPositiveButton("保存",(d,i)->{try{String origin=NetDiskSession.validateOrigin(input.getText().toString());if(origin.equals(NetDiskSession.base(activity)))return;
            TerminalClient.IO.execute(()->{try{NetDiskSession.logout(activity);}catch(Exception ignored){}NetDiskSession.clear(activity);NetDiskSession.prefs(activity).edit().putString("origin",origin).putBoolean("signed_out",false).commit();activity.runOnUiThread(()->{folders.clear();items.clear();show();});});}catch(Exception e){activity.error(e);}}).create());}
    boolean back(){if(!folders.isEmpty()){if(folders.size()>1)folders.remove(folders.size()-1);else folders.clear();items.clear();show();return true;}return false;}
    void stop(){viewEpoch++;for(AlertDialog dialog:new ArrayList<>(dialogs))dialog.dismiss();}
    void destroy(){stop();pendingDownload=null;pendingAccount=null;}
}
