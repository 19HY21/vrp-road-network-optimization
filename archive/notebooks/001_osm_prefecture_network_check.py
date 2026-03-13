#!/usr/bin/env python3
"""OpenStreetMapから都道府県単位の道路ネットワークを取得するPoCスクリプト."""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import osmnx as ox


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "OpenStreetMapから指定した都道府県の自動車道路ネットワークを取得し、"
            "サイズ確認と最短経路計算を行います。"
        )
    )
    parser.add_argument(
        "place",
        nargs="?",
        default="Tokyo, Japan",
        help='取得対象の地域名。例: "Tokyo, Japan"',
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="ランダムノード選択のシード値",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/figures/osm_prefecture_network_check"),
        help="画像出力先ディレクトリ",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="matplotlibの画面表示を行わず、画像保存のみ行う",
    )
    return parser.parse_args()


def largest_strongly_connected_subgraph(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    components = nx.strongly_connected_components(graph)
    largest_component_nodes = max(components, key=len)
    return graph.subgraph(largest_component_nodes).copy()


def save_network_plot(graph: nx.MultiDiGraph, output_path: Path) -> None:
    fig, _ = ox.plot_graph(
        graph,
        node_size=0,
        edge_color="dimgray",
        edge_linewidth=0.4,
        bgcolor="white",
        show=False,
        close=False,
    )
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def save_route_plot(graph: nx.MultiDiGraph, route: list[int], output_path: Path) -> None:
    fig, _ = ox.plot_graph_route(
        graph,
        route,
        route_color="crimson",
        route_linewidth=3,
        node_size=0,
        edge_color="lightgray",
        edge_linewidth=0.4,
        bgcolor="white",
        show=False,
        close=False,
    )
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"地域名: {args.place}")
    print("OpenStreetMapから道路ネットワークを取得しています...")

    graph = ox.graph_from_place(args.place, network_type="drive", simplify=True)

    print("取得完了")
    print(f"ノード数: {graph.number_of_nodes():,}")
    print(f"エッジ数: {graph.number_of_edges():,}")

    network_image = args.output_dir / "road_network.png"
    save_network_plot(graph, network_image)
    print(f"道路ネットワーク画像を保存しました: {network_image}")

    routed_graph = largest_strongly_connected_subgraph(graph)
    routed_nodes = list(routed_graph.nodes)
    if len(routed_nodes) < 2:
        raise RuntimeError("最短経路計算に必要なノード数が不足しています。")

    origin, destination = random.sample(routed_nodes, 2)
    print("最短経路を計算しています...")

    route = nx.shortest_path(
        routed_graph,
        source=origin,
        target=destination,
        weight="length",
    )
    route_length_m = nx.shortest_path_length(
        routed_graph,
        source=origin,
        target=destination,
        weight="length",
    )

    print(f"出発ノード: {origin}")
    print(f"到着ノード: {destination}")
    print(f"最短経路距離: {route_length_m:,.2f} m")

    route_image = args.output_dir / "shortest_route.png"
    save_route_plot(routed_graph, route, route_image)
    print(f"最短経路画像を保存しました: {route_image}")

    if not args.no_show:
        plt.figure(figsize=(8, 8))
        plt.imshow(plt.imread(network_image))
        plt.axis("off")
        plt.title("Road Network")

        plt.figure(figsize=(8, 8))
        plt.imshow(plt.imread(route_image))
        plt.axis("off")
        plt.title("Shortest Route")
        plt.show()


if __name__ == "__main__":
    main()
