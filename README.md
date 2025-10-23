# 💥 SMS_Bombar (Educational Lab Simulator)

**Purpose:**  
A simulation tool for learning about rate limits, protection lists, and message queuing — intended for ethical use **inside labs or isolated networks** only.

---

## 🧩 Installation (Kali / Ubuntu)

```bash
git clone https://github.com/<your-username>/SMS_Bombar.git
cd SMS_Bombar
bash install.sh
```

---

## ▶️ Run the Server
```bash
bash run.sh
```

Then open: [http://127.0.0.1:5000](http://127.0.0.1:5000)

---

## 🧰 CLI Examples

Initialize DB manually (if needed):
```bash
python3 SMS_Bombar.py --db ./sms_lab.db init-db
```

Send test message:
```bash
python3 SMS_Bombar.py --db ./sms_lab.db send --to 2001 --body "Hello Test" --count 5
```

---

## ⚠️ Disclaimer
This project is for **educational & lab purposes only**.  
Do **NOT** use it for spamming, harassment, or real-world exploitation.  
The author assumes no responsibility for misuse.
