import streamlit as st
import sqlite3, os, hashlib, io
from datetime import date, datetime
import pandas as pd
import plotly.express as px
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

APP_NAME = "GTC Solar System ERP"
DB = "gtc_erp.db"

st.set_page_config(page_title=APP_NAME, page_icon="☀️", layout="wide")

# ---------- Database ----------
def db():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

con = db()
con.executescript('''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, name TEXT, phone TEXT, address TEXT, opening_balance REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY, name TEXT, phone TEXT, address TEXT, opening_balance REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, sku TEXT UNIQUE, name TEXT, category TEXT, unit TEXT, buy_price REAL DEFAULT 0, sale_price REAL DEFAULT 0, stock REAL DEFAULT 0, min_stock REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, invoice_no TEXT UNIQUE, sale_date TEXT, customer_id INTEGER, payment_method TEXT, discount REAL DEFAULT 0, tax REAL DEFAULT 0, total REAL DEFAULT 0, paid REAL DEFAULT 0, notes TEXT);
CREATE TABLE IF NOT EXISTS sale_items(id INTEGER PRIMARY KEY, sale_id INTEGER, product_id INTEGER, qty REAL, rate REAL, cost_rate REAL);
CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY, purchase_no TEXT UNIQUE, purchase_date TEXT, supplier_id INTEGER, payment_method TEXT, total REAL DEFAULT 0, paid REAL DEFAULT 0, notes TEXT);
CREATE TABLE IF NOT EXISTS purchase_items(id INTEGER PRIMARY KEY, purchase_id INTEGER, product_id INTEGER, qty REAL, rate REAL);
CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY, expense_date TEXT, category TEXT, description TEXT, payment_method TEXT, amount REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS gatepasses(id INTEGER PRIMARY KEY, gp_no TEXT UNIQUE, gp_date TEXT, customer TEXT, project TEXT, vehicle TEXT, driver TEXT, purpose TEXT, returnable TEXT, authorized_by TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS gatepass_items(id INTEGER PRIMARY KEY, gatepass_id INTEGER, product_id INTEGER, qty REAL);
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY, txn_date TEXT, account_type TEXT, account_name TEXT, ref_type TEXT, ref_no TEXT, debit REAL DEFAULT 0, credit REAL DEFAULT 0, description TEXT);
CREATE TABLE IF NOT EXISTS stock_moves(id INTEGER PRIMARY KEY, txn_date TEXT, product_id INTEGER, move_type TEXT, qty REAL, ref_no TEXT, notes TEXT);
''')
# default admin
if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
    con.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)", ("admin", hashlib.sha256(b"admin123").hexdigest(), "Admin"))
    con.commit()


def q(sql, params=(), one=False):
    cur = con.execute(sql, params)
    rows = cur.fetchall()
    return rows[0] if one and rows else (None if one else rows)

def execsql(sql, params=()):
    cur = con.execute(sql, params); con.commit(); return cur.lastrowid

def money(x): return f"Rs. {x:,.0f}"

def next_no(prefix, table, col):
    n = q(f"SELECT COUNT(*) n FROM {table}", one=True)["n"] + 1
    return f"{prefix}-{datetime.now():%Y%m}-{n:04d}"

def ledger(account_type, account_name, ref_type, ref_no, debit, credit, desc, d=None):
    execsql("INSERT INTO ledger(txn_date,account_type,account_name,ref_type,ref_no,debit,credit,description) VALUES(?,?,?,?,?,?,?,?)",
            (d or str(date.today()), account_type, account_name, ref_type, ref_no, debit, credit, desc))

def stock_move(pid, qty, typ, ref, notes=""):
    execsql("INSERT INTO stock_moves(txn_date,product_id,move_type,qty,ref_no,notes) VALUES(?,?,?,?,?,?)", (str(date.today()),pid,typ,qty,ref,notes))
    sign = 1 if typ in ("Purchase","Return In") else -1
    con.execute("UPDATE products SET stock=stock+? WHERE id=?", (sign*qty,pid)); con.commit()

# ---------- Login ----------
if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    st.markdown("# ☀️ GTC Solar System ERP")
    st.caption("GTC Solar System SMC Private Limited")
    st.divider()
    c1,c2,c3 = st.columns([1,1,1])
    with c2:
        with st.form("login"):
            u=st.text_input("Username", value="admin")
            p=st.text_input("Password", type="password", value="admin123")
            ok=st.form_submit_button("🔐 Sign in", use_container_width=True)
            if ok:
                h=hashlib.sha256(p.encode()).hexdigest()
                user=q("SELECT * FROM users WHERE username=? AND password=?",(u,h),one=True)
                if user:
                    st.session_state.user=dict(user); st.rerun()
                else: st.error("Invalid username or password")
    st.info("First login: admin / admin123 — change this in the Users module before production use.")
    st.stop()

# ---------- Sidebar ----------
st.sidebar.title("☀️ GTC ERP")
st.sidebar.caption(f"{st.session_state.user['username']} • {st.session_state.user['role']}")
menu=st.sidebar.radio("Navigation", ["Dashboard","Sales","Purchases","Inventory","Gate Pass","Expenses","Ledger","Customers","Suppliers","Reports","Users"])
if st.sidebar.button("🚪 Logout"):
    st.session_state.user=None; st.rerun()

# ---------- Dashboard ----------
def dashboard():
    st.title("📊 Dashboard")
    month=datetime.now().strftime('%Y-%m')
    sales=q("SELECT COALESCE(SUM(total),0) x FROM sales WHERE substr(sale_date,1,7)=?",(month,),one=True)["x"]
    purchases=q("SELECT COALESCE(SUM(total),0) x FROM purchases WHERE substr(purchase_date,1,7)=?",(month,),one=True)["x"]
    expenses=q("SELECT COALESCE(SUM(amount),0) x FROM expenses WHERE substr(expense_date,1,7)=?",(month,),one=True)["x"]
    stock_value=q("SELECT COALESCE(SUM(stock*buy_price),0) x FROM products",one=True)["x"]
    receiv=q("SELECT COALESCE(SUM(total-paid),0) x FROM sales",one=True)["x"]
    pay=q("SELECT COALESCE(SUM(total-paid),0) x FROM purchases",one=True)["x"]
    a=st.columns(6)
    for col,label,val in zip(a,["Monthly Sales","Monthly Purchases","Monthly Expenses","Inventory Value","Receivables","Payables"],[sales,purchases,expenses,stock_value,receiv,pay]):
        col.metric(label,money(val))
    st.divider()
    left,right=st.columns(2)
    with left:
        df=pd.read_sql_query("SELECT substr(sale_date,1,7) month,SUM(total) sales FROM sales GROUP BY month ORDER BY month",con)
        if not df.empty: st.plotly_chart(px.bar(df,x="month",y="sales",title="Sales by Month"),use_container_width=True)
    with right:
        low=pd.read_sql_query("SELECT sku,name,stock,min_stock FROM products WHERE stock<=min_stock ORDER BY stock",con)
        st.subheader("⚠️ Low Stock")
        st.dataframe(low,use_container_width=True,hide_index=True) if not low.empty else st.success("No low-stock products.")

# ---------- Sales ----------
def sales_page():
    st.title("💰 Sales")
    tabs=st.tabs(["New Sale","Sales Register"])
    with tabs[0]:
        customers=q("SELECT * FROM customers ORDER BY name")
        products=q("SELECT * FROM products ORDER BY name")
        if not customers or not products:
            st.warning("Add at least one customer and one product first."); return
        with st.form("sale"):
            c1,c2,c3=st.columns(3)
            dt=c1.date_input("Sale date",date.today()); cust=c2.selectbox("Customer",customers,format_func=lambda x:x['name']); paym=c3.selectbox("Payment",["Cash","Bank","Credit","Cheque"])
            rows=[]
            for i in range(8):
                cc=st.columns([3,1,1])
                prod=cc[0].selectbox(f"Product {i+1}",[None]+products,key=f"sp{i}",format_func=lambda x:"— Select —" if x is None else f"{x['sku']} | {x['name']} (stock {x['stock']})")
                qty=cc[1].number_input("Qty",min_value=0.0,step=1.0,key=f"sq{i}")
                rate=cc[2].number_input("Rate",min_value=0.0,step=100.0,value=float(prod['sale_price']) if prod else 0.0,key=f"sr{i}")
                if prod and qty>0: rows.append((prod,qty,rate))
            discount=st.number_input("Discount",min_value=0.0,step=100.0); tax=st.number_input("Tax",min_value=0.0,step=100.0); paid=st.number_input("Paid",min_value=0.0,step=100.0); notes=st.text_input("Notes")
            total=sum(qty*rate for _,qty,rate in rows)-discount+tax
            st.info(f"Invoice total: {money(total)} | Balance: {money(max(total-paid,0))}")
            save=st.form_submit_button("✅ Save Sale",use_container_width=True)
            if save:
                if any(qty>prod['stock'] for prod,qty,_ in rows): st.error("Insufficient stock.")
                elif not rows: st.error("Add at least one item.")
                else:
                    inv=next_no("INV", "sales","invoice_no")
                    sid=execsql("INSERT INTO sales(invoice_no,sale_date,customer_id,payment_method,discount,tax,total,paid,notes) VALUES(?,?,?,?,?,?,?,?,?)",(inv,str(dt),cust['id'],paym,discount,tax,total,paid,notes))
                    for prod,qty,rate in rows:
                        execsql("INSERT INTO sale_items(sale_id,product_id,qty,rate,cost_rate) VALUES(?,?,?,?,?)",(sid,prod['id'],qty,rate,prod['buy_price']))
                        stock_move(prod['id'],qty,"Sale",inv)
                    ledger("Customer",cust['name'],"Sale",inv,total,paid,f"Sale {inv}",str(dt))
                    st.success(f"Saved {inv}")
    with tabs[1]:
        df=pd.read_sql_query("SELECT s.invoice_no,s.sale_date,c.name customer,s.payment_method,s.total,s.paid,(s.total-s.paid) balance FROM sales s LEFT JOIN customers c ON c.id=s.customer_id ORDER BY s.id DESC",con)
        st.dataframe(df,use_container_width=True,hide_index=True)
        if not df.empty:
            st.download_button("⬇️ Export CSV",df.to_csv(index=False),"sales.csv","text/csv")

# ---------- Purchases ----------
def purchases_page():
    st.title("🛒 Purchases")
    tabs=st.tabs(["New Purchase","Purchase Register"])
    with tabs[0]:
        suppliers=q("SELECT * FROM suppliers ORDER BY name"); products=q("SELECT * FROM products ORDER BY name")
        if not suppliers or not products: st.warning("Add at least one supplier and one product first."); return
        with st.form("purchase"):
            c1,c2,c3=st.columns(3); dt=c1.date_input("Purchase date",date.today()); sup=c2.selectbox("Supplier",suppliers,format_func=lambda x:x['name']); pm=c3.selectbox("Payment",["Cash","Bank","Credit","Cheque"])
            rows=[]
            for i in range(8):
                cc=st.columns([3,1,1]); prod=cc[0].selectbox(f"Product {i+1}",[None]+products,key=f"pp{i}",format_func=lambda x:"— Select —" if x is None else f"{x['sku']} | {x['name']}"); qty=cc[1].number_input("Qty",min_value=0.0,step=1.0,key=f"pq{i}"); rate=cc[2].number_input("Rate",min_value=0.0,step=100.0,value=float(prod['buy_price']) if prod else 0.0,key=f"pr{i}")
                if prod and qty>0: rows.append((prod,qty,rate))
            paid=st.number_input("Paid",min_value=0.0,step=100.0); notes=st.text_input("Notes"); total=sum(qty*rate for _,qty,rate in rows); st.info(f"Purchase total: {money(total)} | Balance: {money(max(total-paid,0))}")
            save=st.form_submit_button("✅ Save Purchase",use_container_width=True)
            if save:
                if not rows: st.error("Add at least one item.")
                else:
                    no=next_no("PUR","purchases","purchase_no"); pid=execsql("INSERT INTO purchases(purchase_no,purchase_date,supplier_id,payment_method,total,paid,notes) VALUES(?,?,?,?,?,?,?)",(no,str(dt),sup['id'],pm,total,paid,notes))
                    for prod,qty,rate in rows:
                        execsql("INSERT INTO purchase_items(purchase_id,product_id,qty,rate) VALUES(?,?,?,?)",(pid,prod['id'],qty,rate)); stock_move(prod['id'],qty,"Purchase",no)
                    ledger("Supplier",sup['name'],"Purchase",no,paid,total,f"Purchase {no}",str(dt)); st.success(f"Saved {no}")
    with tabs[1]:
        df=pd.read_sql_query("SELECT p.purchase_no,p.purchase_date,s.name supplier,p.payment_method,p.total,p.paid,(p.total-p.paid) balance FROM purchases p LEFT JOIN suppliers s ON s.id=p.supplier_id ORDER BY p.id DESC",con); st.dataframe(df,use_container_width=True,hide_index=True)

# ---------- Inventory ----------
def inventory_page():
    st.title("📦 Inventory")
    tabs=st.tabs(["Products","Stock Movement"])
    with tabs[0]:
        with st.form("product"):
            c=st.columns(5); sku=c[0].text_input("SKU"); name=c[1].text_input("Product name"); cat=c[2].selectbox("Category",["Solar Panel","Inverter","Battery","Structure","Cable","Breaker/DB","Accessory","Other"]); unit=c[3].text_input("Unit",value="pcs"); buy=c[4].number_input("Buy price",min_value=0.0); sale=st.number_input("Sale price",min_value=0.0); opening=st.number_input("Opening stock",min_value=0.0); minimum=st.number_input("Minimum stock",min_value=0.0)
            if st.form_submit_button("➕ Add Product",use_container_width=True):
                try: execsql("INSERT INTO products(sku,name,category,unit,buy_price,sale_price,stock,min_stock) VALUES(?,?,?,?,?,?,?,?)",(sku,name,cat,unit,buy,sale,opening,minimum)); st.success("Product added")
                except sqlite3.IntegrityError: st.error("SKU already exists")
        df=pd.read_sql_query("SELECT sku,name,category,unit,buy_price,sale_price,stock,min_stock,stock*buy_price inventory_value FROM products ORDER BY name",con); st.dataframe(df,use_container_width=True,hide_index=True)
    with tabs[1]:
        df=pd.read_sql_query("SELECT sm.txn_date,p.sku,p.name,sm.move_type,sm.qty,sm.ref_no FROM stock_moves sm JOIN products p ON p.id=sm.product_id ORDER BY sm.id DESC",con); st.dataframe(df,use_container_width=True,hide_index=True)

# ---------- Gate Pass ----------
def gate_page():
    st.title("🚚 Gate Pass")
    products=q("SELECT * FROM products ORDER BY name")
    with st.form("gp"):
        c=st.columns(3); dt=c[0].date_input("Date",date.today()); customer=c[1].text_input("Customer"); project=c[2].text_input("Project / Site"); vehicle=st.text_input("Vehicle number"); driver=st.text_input("Driver"); purpose=st.text_input("Purpose",value="Delivery"); ret=st.selectbox("Returnable?",["No","Yes"]); auth=st.text_input("Authorized by")
        rows=[]
        for i in range(6):
            cc=st.columns(2); prod=cc[0].selectbox(f"Item {i+1}",[None]+products,key=f"gp{i}",format_func=lambda x:"— Select —" if x is None else f"{x['sku']} | {x['name']} (stock {x['stock']})"); qty=cc[1].number_input("Qty",min_value=0.0,step=1.0,key=f"gq{i}")
            if prod and qty>0: rows.append((prod,qty))
        notes=st.text_input("Notes"); save=st.form_submit_button("✅ Create Gate Pass",use_container_width=True)
        if save:
            if not rows: st.error("Add at least one item.")
            elif any(qty>prod['stock'] for prod,qty in rows): st.error("Insufficient stock.")
            else:
                no=next_no("GP","gatepasses","gp_no"); gid=execsql("INSERT INTO gatepasses(gp_no,gp_date,customer,project,vehicle,driver,purpose,returnable,authorized_by,notes) VALUES(?,?,?,?,?,?,?,?,?,?)",(no,str(dt),customer,project,vehicle,driver,purpose,ret,auth,notes))
                for prod,qty in rows: execsql("INSERT INTO gatepass_items(gatepass_id,product_id,qty) VALUES(?,?,?)",(gid,prod['id'],qty)); stock_move(prod['id'],qty,"Sale",no,"Gate pass dispatch")
                st.success(f"Gate pass {no} created")
    df=pd.read_sql_query("SELECT gp_no,gp_date,customer,project,vehicle,driver,purpose,returnable,authorized_by FROM gatepasses ORDER BY id DESC",con); st.dataframe(df,use_container_width=True,hide_index=True)

# ---------- Expenses ----------
def expenses_page():
    st.title("💸 Expenses")
    with st.form("expense"):
        c=st.columns(3); dt=c[0].date_input("Date",date.today()); cat=c[1].selectbox("Category",["Salaries","Rent","Electricity","Fuel","Transport","Marketing","Maintenance","Internet/Mobile","Office","Miscellaneous"]); method=c[2].selectbox("Payment",["Cash","Bank","Cheque"]); desc=st.text_input("Description"); amount=st.number_input("Amount",min_value=0.0,step=100.0); notes=st.text_input("Notes")
        if st.form_submit_button("✅ Save Expense",use_container_width=True):
            no=f"EXP-{datetime.now():%Y%m%d%H%M%S}"; execsql("INSERT INTO expenses(expense_date,category,description,payment_method,amount,notes) VALUES(?,?,?,?,?,?)",(str(dt),cat,desc,method,amount,notes)); ledger("Expense",cat,"Expense",no,amount,0,desc,str(dt)); st.success("Expense saved")
    df=pd.read_sql_query("SELECT expense_date,category,description,payment_method,amount,notes FROM expenses ORDER BY id DESC",con); st.dataframe(df,use_container_width=True,hide_index=True)

# ---------- Ledger ----------
def ledger_page():
    st.title("📒 Ledger")
    df=pd.read_sql_query("SELECT txn_date,account_type,account_name,ref_type,ref_no,debit,credit,(debit-credit) balance,description FROM ledger ORDER BY id DESC",con)
    st.dataframe(df,use_container_width=True,hide_index=True)
    if not df.empty:
        st.download_button("⬇️ Export Ledger Excel",pd.DataFrame(df).to_csv(index=False),"ledger.csv","text/csv")

# ---------- Masters ----------
def master_page(kind):
    title="Customers" if kind=="customers" else "Suppliers"; table=kind; st.title(("👥 " if kind=="customers" else "🏢 ")+title)
    with st.form(kind):
        c=st.columns(4); name=c[0].text_input("Name"); phone=c[1].text_input("Phone"); address=c[2].text_input("Address"); opening=c[3].number_input("Opening balance",min_value=0.0,step=100.0)
        if st.form_submit_button("➕ Add",use_container_width=True):
            execsql(f"INSERT INTO {table}(name,phone,address,opening_balance) VALUES(?,?,?,?)",(name,phone,address,opening)); st.success("Saved")
    df=pd.read_sql_query(f"SELECT id,name,phone,address,opening_balance FROM {table} ORDER BY name",con); st.dataframe(df,use_container_width=True,hide_index=True)

# ---------- Reports ----------
def reports_page():
    st.title("📈 Reports")
    start=st.date_input("From",date(datetime.now().year,datetime.now().month,1)); end=st.date_input("To",date.today())
    s=q("SELECT COALESCE(SUM(total),0) x FROM sales WHERE sale_date BETWEEN ? AND ?",(str(start),str(end)),one=True)["x"]; p=q("SELECT COALESCE(SUM(total),0) x FROM purchases WHERE purchase_date BETWEEN ? AND ?",(str(start),str(end)),one=True)["x"]; e=q("SELECT COALESCE(SUM(amount),0) x FROM expenses WHERE expense_date BETWEEN ? AND ?",(str(start),str(end)),one=True)["x"]
    a=st.columns(4); a[0].metric("Sales",money(s)); a[1].metric("Purchases",money(p)); a[2].metric("Expenses",money(e)); a[3].metric("Sales − Expenses",money(s-e))
    df=pd.read_sql_query("SELECT substr(sale_date,1,7) month,SUM(total) sales FROM sales GROUP BY month ORDER BY month",con); 
    if not df.empty: st.plotly_chart(px.line(df,x="month",y="sales",markers=True,title="Monthly Sales Trend"),use_container_width=True)
    st.subheader("Top-selling products")
    top=pd.read_sql_query("SELECT p.name,SUM(si.qty) qty,SUM(si.qty*si.rate) sales FROM sale_items si JOIN products p ON p.id=si.product_id GROUP BY p.id ORDER BY qty DESC LIMIT 10",con); st.dataframe(top,use_container_width=True,hide_index=True)

# ---------- Users ----------
def users_page():
    st.title("👤 Users")
    with st.form("useradd"):
        c=st.columns(3); u=c[0].text_input("Username"); pw=c[1].text_input("Password",type="password"); role=c[2].selectbox("Role",["Admin","Manager","Sales","Warehouse","Accounts"])
        if st.form_submit_button("➕ Add User",use_container_width=True):
            try: execsql("INSERT INTO users(username,password,role) VALUES(?,?,?)",(u,hashlib.sha256(pw.encode()).hexdigest(),role)); st.success("User added")
            except sqlite3.IntegrityError: st.error("Username exists")
    df=pd.read_sql_query("SELECT id,username,role FROM users",con); st.dataframe(df,use_container_width=True,hide_index=True)

if menu=="Dashboard": dashboard()
elif menu=="Sales": sales_page()
elif menu=="Purchases": purchases_page()
elif menu=="Inventory": inventory_page()
elif menu=="Gate Pass": gate_page()
elif menu=="Expenses": expenses_page()
elif menu=="Ledger": ledger_page()
elif menu=="Customers": master_page("customers")
elif menu=="Suppliers": master_page("suppliers")
elif menu=="Reports": reports_page()
elif menu=="Users": users_page()
