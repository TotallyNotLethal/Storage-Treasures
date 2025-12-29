
class SniperAlerts:
    def __init__(self):
        self.triggered = set()

    def check(self, minutes_left):
        fired = []
        for m in (10, 5, 1):
            if minutes_left <= m and m not in self.triggered:
                self.triggered.add(m)
                fired.append(m)
        return fired
