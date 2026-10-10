#!/usr/bin/env python3
"""Run the loopback-only Snow Gloves pilot coordinator."""
import argparse
from lib.fleet_coordinator import Coordinator, load_config, server

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--port',type=int,default=4101)
    args=parser.parse_args()
    coordinator=Coordinator(load_config(args.config))
    http=server(coordinator,args.port)
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http.server_close()
        coordinator.close()

if __name__=='__main__':
    main()
