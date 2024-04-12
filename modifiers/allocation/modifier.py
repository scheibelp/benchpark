# Copyright 2023 Lawrence Livermore National Security, LLC and other
# Benchpark Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: Apache-2.0

import math
from enum import Enum
from ramble.modkit import *


class AllocOpt(Enum):
    # Experiment resource requests
    N_RANKS = 1
    N_NODES = 2
    N_CORES_PER_RANK = 3
    N_THREADS_PER_PROC = 4  # number of OMP threads per rank
    N_RANKS_PER_NODE = 5
    N_GPUS = 6

    # Descriptions of resources available on systems
    SYS_GPUS_PER_NODE = 100
    SYS_CPUS_PER_NODE = 101

    # Scheduler identification and other high-level instructions
    SCHEDULER = 200
    TIMEOUT = 201  # This is assumed to be in minutes
    MAX_REQUEST = 202

    @staticmethod
    def as_type(enumval, input):
        if enumval == AllocOpt.SCHEDULER:
            return str(input)
        else:
            return int(input)


SENTINEL_UNDEFINED_VALUE_STR = "placeholder"


def defined_allocation_options(expander):
    """For each possible allocation option, check if it was filled in by
    Ramble.
    """
    defined = {}
    for alloc_opt in AllocOpt:
        var_def = expander.expand_var(f"{{{alloc_opt.name.lower()}}}")
        try:
            val = AllocOpt.as_type(alloc_opt, var_def)
        except ValueError:
            continue

        if val is not None:
            defined[alloc_opt] = val

    return defined


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self["_attributes"] = set()

    def __getattr__(self, *args, **kwargs):
        return self.__getitem__(*args, **kwargs)

    def __setattr__(self, *args, **kwargs):
        self.__setitem__(*args, **kwargs)

    def __delattr__(self, *args, **kwargs):
        self.__delitem__(*args, **kwargs)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if key != "_attributes":
            self["_attributes"].add(key)

    def defined(self):
        return list((k, self[k]) for k in self["_attributes"])

    @staticmethod
    def nullify_placeholders(v):
        # If we see a string variable set to "placeholder" we assume the
        # user wants us to set it.
        # For integers, values exceeding max_request are presumed to be
        # placeholders.
        max_request_int = v.max_request or 1000
        placeholder_checks = {
            int: lambda x: x > max_request_int,
            str: lambda x: x == SENTINEL_UNDEFINED_VALUE_STR,
        }
        for var, val in v.defined():
            if val is None:
                continue

            for t, remove_fn in placeholder_checks.items():
                try:
                    read_as = t(val)
                    if remove_fn(read_as):
                        v[var] = None
                except ValueError:
                    pass

    @staticmethod
    def from_predefined_variables(var_defs):
        v = AttrDict()
        for alloc_opt in AllocOpt:
            setattr(v, alloc_opt.name.lower(), var_defs.get(alloc_opt, None))

        AttrDict.nullify_placeholders(v)
        return v


class Allocation(BasicModifier):

    name = "allocation"

    tags("infrastructure")

    # Currently there is only one mode. The only behavior supported right
    # now is to attempt to request "enough" resources for a given
    # request (e.g. to make sure we request enough nodes, assuming we
    # know how many CPUs we want)"
    mode("standard", description="Standard execution mode for allocation")
    default_mode("standard")

    def inherit_from_application(self, app):
        super().inherit_from_application(app)

        var_defs = defined_allocation_options(app.expander)
        v = AttrDict.from_predefined_variables(var_defs)

        # Calculate unset values (e.g. determine n_nodes if not set)
        self.determine_allocation(v)

        self.determine_scheduler_instructions(v)

        # Definitions
        for var, val in v.defined():
            app.define_variable(var, str(val))

        if v.n_threads_per_proc:
            self.env_var_modification(
                'OMP_NUM_THREADS',
                method='set',
                modification='{n_threads_per_proc}',
                mode="standard"
            )


    def determine_allocation(self, v):
        if not v.n_ranks:
            if v.n_ranks_per_node and v.n_nodes:
                v.n_ranks = v.n_nodes * v.n_ranks_per_node

        if not v.n_nodes:
            if v.n_ranks:
                multi_cpus_per_rank = v.n_cores_per_rank or v.n_threads_per_proc or 0
                cpus_request_per_rank = max(multi_cpus_per_rank, 1)
                ranks_per_node = math.floor(v.sys_cpus_per_node / cpus_request_per_rank)
                v.n_nodes = math.ceil(v.n_ranks / ranks_per_node)
            if v.n_gpus:
                v.n_nodes = math.ceil(v.n_gpus / float(v.gpus_per_node))

        if not v.n_threads_per_proc:
            v.n_threads_per_proc = 1

        max_request = v.max_request or 1000
        # Final check, make sure the above arithmetic didn't result in an
        # unreasonable allocation request.
        for var, val in v.defined():
            try:
                int(val)
            except (ValueError, TypeError):
                continue
            if val > max_request:
                raise ValueError(f"Request exceeds maximum: {var}/{val}/{max_request}")


    def slurm_instructions(self, v):
        srun_opts = []
        sbatch_opts = []  # opts just for the sbatch script

        if v.n_ranks:
            srun_opts.append(f"-n {v.n_ranks}")
        if v.n_gpus:
            srun_opts.append(f"--gpus {v.n_gpus}")
        if v.n_nodes:
            srun_opts.append(f"-N {v.n_nodes}")

        if v.timeout:
            sbatch_opts.append(f"--time {v.timeout}")

        sbatch_directives = list(f"#SBATCH {x}" for x in (srun_opts + sbatch_opts))

        v.mpi_command = f"srun {' '.join(srun_opts)}"
        v.batch_submit = "sbatch {execute_experiment}"
        v.allocation_directives = "\n".join(sbatch_directives)

    def flux_instructions(self, v):
        cmd_opts = []
        batch_opts = []

        if v.n_ranks:
            cmd_opts.append(f"-n {v.n_ranks}")
        if v.n_nodes:
            cmd_opts.append(f"-N {v.n_nodes}")

        if v.timeout:
            batch_opts.append("-t {v.timeout}m")

        batch_directives = list(f"# flux: {x}" for x in (cmd_opts + batch_opts))

        v.mpi_command = f"flux run {' '.join(cmd_opts)}"
        v.batch_submit = "flux batch {execute_experiment}"
        v.allocation_directives = "\n".join(batch_directives)

    def mpi_instructions(self, v):
        v.mpi_command = f"mpirun -n {v.n_ranks} --oversubscribe"
        v.batch_submit = "{execute_experiment}"
        v.allocation_directives = ""

    def determine_scheduler_instructions(self, v):
        handler = {
            "slurm": self.slurm_instructions,
            "flux": self.flux_instructions,
            "mpi": self.mpi_instructions,
        }
        if v.scheduler not in handler:
            raise ValueError(
                f"scheduler ({v.scheduler}) must be one of : "
                + " ".join(handler.keys())
            )

        if not v.timeout:
            v.timeout = 120

        handler[v.scheduler](v)
