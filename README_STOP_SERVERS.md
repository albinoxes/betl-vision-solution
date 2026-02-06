# IMMEDIATE ACTIONS - PC Still Slow After Exit

## STOP ALL SERVERS RIGHT NOW

Open PowerShell and run:

```powershell
# Navigate to project directory
cd C:\Users\BoytardAlb\repo\python\belt-vision-solution

# Run the stop script
.\stop_all_servers.ps1
```

**If that doesn't work, use this:**

```powershell
# Force kill all Python processes
Get-Process python | Stop-Process -Force

# Verify they're gone
Get-Process python
# Should show "Get-Process : Cannot find a process with the name 'python'"
```

---

## WHY YOUR PC IS STILL SLOW

You have **4 separate servers** running:
1. **flask-client** (port 5000) - The main app you started
2. **webcam-server** (port 5001) - Still running in background
3. **legacy-camera-server** (port 5002) - Still running in background
4. **simulator-server** (port 5003) - Still running in background

**When you press Ctrl+C, you only stop #1. The other 3 keep running!**

---

## CHECK WHAT'S STILL RUNNING

```powershell
# Check status
.\check_server_status.ps1

# Or manually:
Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -in 5000,5001,5002,5003} | ForEach-Object {
    $proc = Get-Process -Id $_.OwningProcess
    Write-Host "Port $($_.LocalPort): $($proc.ProcessName) (PID: $($proc.Id))"
}
```

---

## PROPER WORKFLOW GOING FORWARD

### Starting Servers:

**Option 1: Start each in separate terminal**
```powershell
# Terminal 1
cd webcam-server
python app.py

# Terminal 2  
cd legacy-camera-server
python app.py

# Terminal 3
cd simulator-server
python app.py

# Terminal 4
cd flask-client
python app.py
```

**Option 2: Start all from one terminal (background)**
```powershell
Start-Process python -ArgumentList "webcam-server\app.py" -WindowStyle Hidden
Start-Process python -ArgumentList "legacy-camera-server\app.py" -WindowStyle Hidden
Start-Process python -ArgumentList "simulator-server\app.py" -WindowStyle Hidden
Start-Sleep 2
python flask-client\app.py  # This one in foreground
```

### Stopping Servers:

**ALWAYS use the stop script:**
```powershell
.\stop_all_servers.ps1
```

**Or press Ctrl+C in EACH terminal if you started them separately**

---

## FIXES APPLIED TODAY

1. ✅ **Read timeout added** - Threads won't block forever on socket reads
2. ✅ **Faster stop detection** - Check every 5 chunks instead of 10
3. ✅ **Aggressive socket cleanup** - Close at all layers
4. ✅ **Force exit** - `os._exit(0)` after cleanup
5. ✅ **Parallel shutdown** - All threads signaled simultaneously
6. ✅ **Memory cleanup** - Garbage collection on exit

---

## IF STILL HAVING ISSUES

### Nuclear Option:
```powershell
# Restart your PC
Restart-Computer
```

### Check for zombie processes:
```powershell
# After restart, before starting servers
Get-Process python
# Should return nothing

# Check ports are free
Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -in 5000,5001,5002,5003}
# Should return nothing
```

---

## TESTING THE FIXES

1. **Run stop script first** to ensure clean slate:
   ```powershell
   .\stop_all_servers.ps1
   ```

2. **Start only the main app**:
   ```powershell
   cd flask-client
   python app.py
   ```

3. **Open web UI** and start a video thread

4. **Press Ctrl+C** and observe:
   - Should see "Stopping all threads..."
   - Should see "Forcing exit..."
   - Should exit in < 15 seconds
   - PC should not be slow

5. **Verify cleanup**:
   ```powershell
   Get-Process python  # Should be empty
   ```

---

## RECOMMENDED: Use Task Manager

1. Open **Task Manager** (Ctrl+Shift+Esc)
2. Go to **Details** tab
3. Find **python.exe** processes
4. Before stopping servers, note how many are running
5. After stopping, verify they're all gone
6. Check **Memory** usage goes down

---

## Files You Can Use

- `stop_all_servers.ps1` - Stops all Python processes
- `check_server_status.ps1` - Shows what's running
- `SHUTDOWN_ISSUES.md` - Detailed technical explanation
- `MEMORY_LEAK_FIXES.md` - Memory leak documentation

---

## Summary

**The Problem:**
You have multiple servers running. Ctrl+C only stops one, others keep consuming resources.

**The Solution:**
Always use `stop_all_servers.ps1` to ensure everything stops.

**The Prevention:**
Fixes applied make individual servers shut down faster and cleaner when they do receive the stop signal.
