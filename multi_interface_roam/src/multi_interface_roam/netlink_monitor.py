#! /usr/bin/env python

import command_with_output
import state_publisher
import threading
import time
import traceback

# TODO 
# Make this autoshutdown when there are no references.

# FIXME Move this elsewhere.
import subprocess
class RunCommand:
    def __init__(self, *args):
        proc = subprocess.Popen(list(args), stdout = subprocess.PIPE, stderr = subprocess.PIPE, close_fds = True)
        (self.stdout, self.stderr) = proc.communicate()

class IFSTATE:
    PLUGGED   = 0
    UP        = 1
    LINK      = 2
    LINK_ADDR = 3
    ADDR      = 4
    COUNT     = 5

class NetlinkMonitor(command_with_output.CommandWithOutput):
    IFSTATE.PLUGGED = 0
    IFSTATE.UP = IFSTATE.PLUGGED + 1
    IFSTATE.LINK = IFSTATE.UP + 1
    IFSTATE.LINK_ADDR = IFSTATE.LINK + 1
    IFSTATE.ADDR = IFSTATE.LINK_ADDR + 1
    IFSTATE.COUNT = IFSTATE.ADDR + 1

    def __init__(self):
        self.lock = threading.RLock()
        self.raw_state_publishers = [ {} for i in range(0, IFSTATE.COUNT)]
        self.state_publishers = [ {} for i in range(0, IFSTATE.COUNT)]
        self.cur_iface = None
        self.deleted = None
        command_with_output.CommandWithOutput.__init__(self, ['ip', 'monitor', 'link', 'addr'], 'ip_monitor')

    def child_restart(self):
        time.sleep(0.2) # Limit race conditions on getting the startup state.
        current_state = RunCommand('ip', 'addr')
        with self.lock:
            old_cur_iface = self.cur_iface
            old_deleted = self.deleted
            for line in current_state.stdout.split('\n'):
                self.got_line(line)
            self.deleted = old_deleted
            self.cur_iface = old_cur_iface

    def get_state_publisher(self, interface, level):
        if level == 0:
            return self.get_raw_state_publisher(interface, level)
        pubs =  self.state_publishers[level]
        if not interface in pubs:
            pubs[interface] = state_publisher.CompositeStatePublisher(lambda l: l[0] and l[1], [
                    self.get_state_publisher(interface, level - 1),
                    self.get_raw_state_publisher(interface, level), 
                    ])
        return pubs[interface]
    
    def get_raw_state_publisher(self, interface, level):
        pubs =  self.raw_state_publishers[level]
        if not interface in pubs:
            pubs[interface] = state_publisher.StatePublisher(False)
        return pubs[interface]
    
    def got_line(self, line):
        with self.lock:
            try:
                # Figure out the interface, and whether this is a delete
                # event.
                
                if len(line) == 0 or (line[0] == ' ' and self.cur_iface == None):
                    return
                tokens = line.rstrip().split()
                link_info = False
                if line[0] != ' ':
                    if tokens[0] == 'Deleted':
                        self.deleted = True
                        tokens.pop(0)
                    else:
                        self.deleted = False
                    self.cur_iface = tokens[1].rstrip(':')
                    if tokens[1][-1] == ':':
                        link_info = True
                    tokens.pop(0)
                    tokens.pop(0)

                if link_info:
                    # Plugged or not?
                    self.get_raw_state_publisher(self.cur_iface, IFSTATE.PLUGGED).set(not self.deleted)
                    
                    # Up or not?
                    flags = tokens[0].strip('<>').split(',')
                    self.get_raw_state_publisher(self.cur_iface, IFSTATE.UP).set('UP' in flags)

                    # Have a link?
                    try:
                        state_idx = tokens.index('state')
                        state = tokens[state_idx + 1]
                        self.get_raw_state_publisher(self.cur_iface, IFSTATE.LINK).set(state != 'DOWN')
                    except ValueError:
                        pass # Sometimes state is not listed.
                
                else:
                    # Find the address.
                    if tokens[0] == 'inet':
                        if self.deleted:
                            addr_state = False
                        else:
                            addr_state = tokens[1].split('/')
                        self.get_raw_state_publisher(self.cur_iface, IFSTATE.ADDR).set(addr_state)

                    if tokens[0].startswith('link/') and len(tokens) > 1:
                        if self.deleted:
                            addr_state = False
                        else:
                            addr_state = tokens[1]
                        self.get_raw_state_publisher(self.cur_iface, IFSTATE.LINK_ADDR).set(addr_state)

            except Exception, e:
                print "Caught exception in NetlinkMonitor.run:", e
                traceback.print_exc(10)
                print

monitor = netlink_monitor = NetlinkMonitor()

if __name__ == "__main__":
    from twisted.internet import reactor
    iface = 'wlan2'
    try:
        while True:
            for i in range(0,IFSTATE.COUNT):
                print monitor.get_raw_state_publisher(iface, i).get(),
                print monitor.get_state_publisher(iface, i).get(), '  /  ',
            print
            reactor.iterate(1)
    except KeyboardInterrupt:
        print "Shutting down on CTRL+C"
        #monitor.shutdown()
