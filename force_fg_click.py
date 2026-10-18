# force_fg_click.py — native Windows click with FORCED foreground (bypasses "Foreground увели")
# Used to click the Stripe hCaptcha checkbox in a real Chrome window when the window keeps
# losing focus (computer_use clicks unreliable). Technique that WORKED:
#   AttachThreadInput to the CURRENT foreground thread (not target's), ALT key trick,
#   SetForegroundWindow, verify GetForegroundWindow()==hwnd, only then mouse_event.
# Usage: python force_fg_click.py <hwnd> <x> <y>
import sys, ctypes

def main():
    hwnd = int(sys.argv[1], 0)
    x, y = int(sys.argv[2]), int(sys.argv[3])
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    cur_fg = u.GetForegroundWindow()
    cur_tid = u.GetWindowThreadProcessId(cur_fg, None)
    tgt_tid = u.GetWindowThreadProcessId(hwnd, None)
    my_tid = k.GetCurrentThreadId()
    u.AttachThreadInput(my_tid, cur_tid, True)
    u.AttachThreadInput(my_tid, tgt_tid, True)
    # ALT trick unlocks SetForegroundWindow restriction
    k.keybd_event(0x12, 0, 0, 0)
    k.keybd_event(0x12, 0, 2, 0)
    ok = u.SetForegroundWindow(hwnd)
    u.BringWindowToTop(hwnd)
    u.ShowWindow(hwnd, 9)  # SW_RESTORE
    fg_now = u.GetForegroundWindow()
    print("setfg:", ok, "fg==hwnd:", fg_now == hwnd)
    if fg_now == hwnd:
        u.SetCursorPos(x, y)
        u.mouse_event(2, 0, 0, 0, 0)   # LEFTDOWN
        u.mouse_event(4, 0, 0, 0, 0)   # LEFTUP
        print("CLICK-SENT", x, y)
    else:
        print("FG-FAIL — window not foreground, click NOT sent")
    u.AttachThreadInput(my_tid, cur_tid, False)
    u.AttachThreadInput(my_tid, tgt_tid, False)

if __name__ == "__main__":
    main()
