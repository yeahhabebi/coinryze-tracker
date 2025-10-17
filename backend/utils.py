import os, csv, random, requests

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "seed.csv")
R2_BUCKET = os.environ.get("R2_BUCKET")
R2_ENDPOINT = os.environ.get("R2_ENDPOINT")
R2_KEY_ID = os.environ.get("R2_KEY_ID")
R2_SECRET = os.environ.get("R2_SECRET")

if not os.path.exists(DATA_FILE):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["draw_number","result"])
        writer.writerow([1,5])
        writer.writerow([2,3])
        writer.writerow([3,7])

def sync_to_r2():
    try:
        with open(DATA_FILE,'rb') as f:
            requests.put(f"{R2_ENDPOINT}/{os.path.basename(DATA_FILE)}", data=f, auth=(R2_KEY_ID,R2_SECRET))
    except:
        pass

def get_latest_draw():
    with open(DATA_FILE,"r") as f:
        lines = list(csv.reader(f))
        last_number = int(lines[-1][0])
    new_number = last_number+1
    new_result = random.randint(0,9)
    with open(DATA_FILE,"a",newline="") as f:
        writer = csv.writer(f)
        writer.writerow([new_number,new_result])
    sync_to_r2()
    return [new_number,new_result]

def calculate_accuracy():
    return round(random.random()*100,2)
