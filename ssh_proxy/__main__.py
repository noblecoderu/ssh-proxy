import argparse


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--endpoint', '-e', required=True,
                        help='AWS IoT endpoint')
    parser.add_argument('--root-cert', '-r', required=True,
                        help='Root CA cert path')
    parser.add_argument('--client', '-c', required=True,
                        help='Client id')
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()


if __name__ == '__main__':
    main()
