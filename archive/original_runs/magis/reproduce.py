"""运行未改动的 MAGIS 类与仓库自带小型 MLP 模型，记录真实 GPU 结果。"""

import json
import time
from pathlib import Path

import torch
from magis.backend import TorchCudaBackend
from magis.optimizer import RelaxOptimizer
from magis.scheduler import RefineMemOpRpoScheduler
from magis.testing import setup_training_graph
from magis.testing.nn import simple_mlp_net
from magis.testing.configs import get_configured_mutator
import magis.op_graph as op_graph
from magis.operators import FissionOp

# Upstream imports operators through a circular path; bind the completed class.
op_graph.FissionOp = FissionOp


def main():
    out = Path(__file__).resolve().parent
    if not torch.cuda.is_available():
        raise RuntimeError("MAGIS TorchCudaBackend requires an available CUDA GPU")
    start = time.perf_counter()
    with TorchCudaBackend(cache_file=str(out / "profile-cache.pkl")) as backend:
        graph, output = simple_mlp_net(batch_size=8, hidden_sizes=[64, 128, 64],
                                       num_classes=10)
        graph = setup_training_graph(graph, output, update_weight=True, inplace=False)
        optimizer = RelaxOptimizer(
            RefineMemOpRpoScheduler(adjust_load_op=False), backend,
            get_configured_mutator(mutator_config_name="mlynar"),
            mem_limit_ratio=0.8, time_budget=20, iter_budget=2,
            number=1, repeat=2)
        best_graph, best_schedule = optimizer.run(graph)
        result = {
            "source_commit": "a332abc73dca97f769054c4f61aef0a52009cf34",
            "model": "repo simple_mlp_net, batch_size=8, hidden_sizes=[64,128,64], num_classes=10, training graph",
            "torch_version": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
            "initial_real_run": optimizer._init_state.run_res._asdict(),
            "best_real_run": optimizer._best_state.run_res._asdict(),
            "initial_sim_latency": optimizer._init_state.sim_res.latency,
            "best_sim_latency": optimizer._best_state.sim_res.latency,
            "best_sim_peak_memory_elements": optimizer._best_state.sim_res.peak_memory,
            "best_num_ops": best_graph.num_nodes,
            "elapsed_wall_seconds": round(time.perf_counter() - start, 3),
            "search_iterations": len(optimizer._records),
        }
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n",
                                         encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
