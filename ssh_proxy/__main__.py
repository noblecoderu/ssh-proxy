import argparse

from ssh_proxy import proxy


def build_parser():
    parser = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
    parser.add_argument('-n', '--client', required=True, dest='name',
                        help='Client id')
    parser.add_argument('-d', '--hostname', required=True, dest='host',
                        help='Server name or ip, accesible from outside')
    parser.add_argument('-t', '--tmp_dir', required=True, dest='runtime_dir',
                        help='Runtime directory')
    parser.add_argument('-i', '--image', required=True, dest='image',
                        help='Docker image name or id')
    parser.add_argument('-e', '--endpoint', required=True, dest='iot_host',
                        help='AWS IoT endpoint')
    parser.add_argument('-r', '--root-cert', required=True, dest='root_ca_path',
                        help='Root CA cert file path')
    parser.add_argument('-c', '--cert', required=True, dest='cert_path',
                        help='Client cert file path')
    parser.add_argument('-k', '--key', required=True, dest='key_path',
                        help='Client key file path')
    parser.add_argument('-a', '--keep-alive', dest='keep_alive', type=int,
                        help='IoT client keep alive time')
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    proxy_ = proxy.Proxy(**vars(args))
    proxy_.catch_signals()
    proxy_.run_forever()


if __name__ == '__main__':
    main()
