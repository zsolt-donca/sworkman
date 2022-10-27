#!/usr/bin/python

# sworkman - Sway Workspace Manager

import argparse
import asyncio

from i3ipc.aio import Connection


async def organize(size, priorities):
    i3 = await Connection().connect()
    workspaces = await i3.get_workspaces()
    outputs = await get_outputs_sorted(i3, priorities)

    for output_index, output in enumerate(outputs):
        workspaces_in_output = [w for w in workspaces if w.output == output.name]
        for workspace_index, workspace in enumerate(workspaces_in_output):
            current_name = workspace.name
            current_num = workspace.num
            new_num = output_index * size + workspace_index
            if current_num != new_num:
                new_name = change_num_in_name(current_name, current_num, new_num)
                await i3.command(f'rename workspace "{current_name}" to "{new_name}"')

    primary_output = outputs[0]
    if not primary_output.focused:
        primary_output_name = primary_output.name
        await i3.command(f'focus output {primary_output_name}')


async def focus_workspace(size, priorities, number):
    i3 = await Connection().connect()
    outputs = await get_outputs_sorted(i3, priorities)

    workspace_number = get_workspace_number(outputs, size, number)
    await i3.command(f'workspace number {workspace_number}')


async def move_current_container_to_workspace(size, priorities, number):
    i3 = await Connection().connect()
    outputs = await get_outputs_sorted(i3, priorities)

    workspace_number = get_workspace_number(outputs, size, number)
    await i3.command(f'move container to workspace number {workspace_number}')


async def focus_output(priorities, direction):
    i3 = await Connection().connect()
    outputs = await get_outputs_sorted(i3, priorities)

    output = get_output_for_direction(outputs, direction)
    output_name = output.name

    await i3.command(f'focus output {output_name}')


async def move_current_workspace_to_output(priorities, direction, size):
    i3 = await Connection().connect()
    outputs = await get_outputs_sorted(i3, priorities)
    workspaces = await i3.get_workspaces()

    orig_output_name = get_focused_output(outputs).name
    dest_output_name = get_output_for_direction(outputs, direction).name

    dest_workspace_num = select_destination_output(dest_output_name, outputs, workspaces, size)

    # this renames the focused workspace to the next available workspace num on the given output
    for workspace in workspaces:
        if workspace.focused:
            current_name = workspace.name
            new_name = change_num_in_name(current_name, workspace.num, dest_workspace_num)
            print(f'rename workspace "{current_name}" to "{new_name}"')
            await i3.command(f'rename workspace "{current_name}" to "{new_name}"')

    # this moves the focused workspace to the selected output (which already has the right name for the output)
    print(f'move workspace to output {dest_output_name}')
    await i3.command(f'move workspace to output {dest_output_name}')

    # check if the original output became empty after the above operations, and if so, rename it according to its index
    await rename_any_empty_workspace(i3, outputs, size)


async def rename_any_empty_workspace(i3, outputs, size):
    workspaces = await i3.get_workspaces()
    for workspace in workspaces:
        if is_workspace_empty(workspace):
            workspace_output = workspace.output
            is_workspace_single_on_output = len([w for w in workspaces if w.output == workspace_output]) == 1
            if is_workspace_single_on_output:
                for output_index, output in enumerate(outputs):
                    if output.name == workspace_output:
                        current_name = workspace.name
                        current_num = workspace.num
                        new_num = output_index * size  # use the starting number for the output
                        if current_num != new_num:
                            new_name = change_num_in_name(current_name, current_num, new_num)
                            await i3.command(f'rename workspace "{current_name}" to "{new_name}"')


def select_destination_output(output_name, outputs, workspaces, size):
    output_index = get_output_index(output_name, outputs)

    workspaces_in_output = [w for w in workspaces if w.output == output_name and not is_workspace_empty(w)]
    workspaces_in_output.sort(key=lambda w: w.num)

    workspace_nums_in_output = {w.num for w in workspaces_in_output}
    output_num_range = set(range(size * output_index, size * (output_index + 1)))

    unused_nums = output_num_range.difference(workspace_nums_in_output)

    if unused_nums:
        # if there are some unused numbers, let's use the smallest
        return min(unused_nums)
    elif len(workspaces_in_output) > 0:
        # if all numbers are taken, let's use the last number + 1 if all numbers are taken
        return workspaces_in_output[-1].num + 1
    else:
        # if all else fails, let's just use the starting number for the output
        return output_index * size


# moves the current container to a new workspace on the destination output
async def move_current_container_to_output(priorities, direction, size):
    i3 = await Connection().connect()
    outputs = await get_outputs_sorted(i3, priorities)
    workspaces = await i3.get_workspaces()

    orig_output_name = get_focused_output(outputs).name
    dest_output_name = get_output_for_direction(outputs, direction).name

    dest_workspace_num = select_destination_output(dest_output_name, outputs, workspaces, size)

    # moves the current container to a new workspace (as workspace named new_workspace_num does not exist)
    await i3.command(f'move container to workspace number {dest_workspace_num}')

    # focus the workspace
    await i3.command(f'workspace number {dest_workspace_num}')

    # this moves the focused workspace to the selected output
    await i3.command(f'move workspace to output {dest_output_name}')

    # check if the original output became empty after the above operations, and if so, rename it according to its index
    await rename_any_empty_workspace(i3, outputs, size)


async def insert_current_workspace(priorities, size, number):
    i3 = await Connection().connect()
    outputs = await get_outputs_sorted(i3, priorities)
    workspaces = await i3.get_workspaces()

    workspace_name_by_num = {w.num: w.name for w in workspaces}
    current_workspace = [w for w in workspaces if w.focused][0]
    current_workspace_name = current_workspace.name
    current_workspace_num = current_workspace.num

    output_name = current_workspace.output
    output_index = get_output_index(output_name, outputs)

    destination_workspace_num = output_index * size + number

    # if the current workspace is the same as the destination, there is nothing to do
    if current_workspace_num == destination_workspace_num:
        return

    # if the destination workspace does not exist (or is empty), let's just rename the current one to it and return
    if destination_workspace_num not in workspace_name_by_num.keys():
        new_name = change_num_in_name(current_workspace_name, current_workspace_num, destination_workspace_num)
        await i3.command(f'rename workspace "{current_workspace_name}" to "{new_name}"')
        return

    # obtains a temporary workspace numer - used when the range of workspaces is full
    def temp_num():
        workspace_num_ceil = max(workspace_name_by_num.keys()) + 2
        free_nums = list(filter(lambda n: n not in workspace_name_by_num.keys(), range(0, workspace_num_ceil)))
        return free_nums[0]

    # build the range of source and destination workspaces for the subsequent rename commands
    if current_workspace_num < destination_workspace_num:
        workspace_range = list(range(current_workspace_num, destination_workspace_num + 1))
        unused = list(filter(lambda n: n not in workspace_name_by_num.keys(), workspace_range))

        # if there are no unused workspace numbers in this range, we'll need to use a temporary workspace name
        if not unused:
            swap_num = temp_num()
            source_range = workspace_range + [swap_num]
            dest_range = [swap_num] + workspace_range
        else:
            swap_num = max(unused)
            source_range = list(range(swap_num + 1, destination_workspace_num + 1)) + [current_workspace_num]
            dest_range = list(range(swap_num, destination_workspace_num + 1))
    else:
        workspace_range = list(range(current_workspace_num, destination_workspace_num - 1, -1))
        unused = list(filter(lambda n: n not in workspace_name_by_num.keys(), workspace_range))

        if not unused:
            swap_num = temp_num()
            source_range = workspace_range + [swap_num]
            dest_range = [swap_num] + workspace_range
        else:
            swap_num = min(unused)
            source_range = list(range(swap_num - 1, destination_workspace_num - 1, -1)) + [current_workspace_num]
            dest_range = list(range(swap_num, destination_workspace_num - 1, -1))

    for source, dest in zip(source_range, dest_range):
        # we used a temporary name for the current workspace (there were no unused numbers)
        if not unused and source == swap_num:
            current_name = change_num_in_name(current_workspace_name, current_workspace_num, swap_num)
        else:
            current_name = workspace_name_by_num[source]

        new_name = change_num_in_name(current_name, source, dest)
        await i3.command(f'rename workspace "{current_name}" to "{new_name}"')

async def get_outputs_sorted(i3, priorities):
    # get the outputs
    outputs = await i3.get_outputs()

    # put all priorities into a dict
    output_names_by_priority = {}
    for priority_entry in priorities:
        parts = priority_entry.split(':', 1)
        if len(parts) == 2:
            output = parts[0]
            priority = int(parts[1])
            output_names_by_priority[output] = priority

    # add all other outputs to the dict by the index returned to us by IPC
    for outputs_index in range(len(outputs)):
        output = outputs[outputs_index]
        if output.name not in output_names_by_priority.keys():
            output_names_by_priority[output.name] = outputs_index

    # sort all outputs
    outputs.sort(key=lambda x: output_names_by_priority[x.name])
    return outputs


def get_output_index(output_name, outputs):
    output_indices = [i for i, o in enumerate(outputs) if o.name == output_name]
    if len(output_indices) > 0:
        return output_indices[0]
    else:
        raise Exception(f"bug: could not get output index: {output_name}, {outputs}")


def get_focused_output(outputs):
    focused_outputs = [o for o in outputs if o.focused]
    if len(focused_outputs) == 1:
        return focused_outputs[0]
    else:
        raise Exception(f"bug: could not get focused outputs: {outputs}")


def is_workspace_empty(workspace):
    rep = workspace.ipc_data["representation"]
    return not workspace.ipc_data["floating_nodes"] and (not rep or rep == "H[]" or rep == "V[]" or rep == "S[]")


# returns the absolute workspace number (e.g. 24) given a relative number (e.g. 4) and size (e.g. 20)
# requires outputs to be sorted (by priority)
def get_workspace_number(outputs, size, number):
    for output_index, output in enumerate(outputs):
        if output.focused:
            workspace_number = output_index * size + number
            return workspace_number

    raise Exception(f"bug: could not find workspace number; {outputs}, {size}, {number}")


# returns the
def get_output_for_direction(outputs, direction):
    if direction == 'next':
        offset = 1
    elif direction == 'prev':
        offset = -1
    else:
        raise Exception(f"bug: invalid direction: {direction}")

    for output_index, output in enumerate(outputs):
        if output.focused:
            index_at_direction = (output_index + offset) % len(outputs)
            output_at_direction = outputs[index_at_direction]
            return output_at_direction

    raise Exception(f"bug: could not find output for direction: {outputs}, {direction}")


def change_num_in_name(name, current_num, new_num):
    parts = name.split(':', 1)
    if len(parts) == 2 and parts[0] == str(current_num):
        return f"{new_num}:{parts[1]}"
    elif name == str(current_num):
        return f"{new_num}"
    else:
        return f"{new_num}:{name}"


def get_next_workspace_number_for_output(workspaces, output_name):
    workspace_nums_in_output = [w.num for w in workspaces if w.output == output_name]
    if len(workspace_nums_in_output) > 0:
        next_workspace_num = max(workspace_nums_in_output) + 1
        return next_workspace_num

    raise Exception(f"bug: could not find next workspace number for output; {workspaces}, {output_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Manage your Sway/i3 Workspaces')
    parser.add_argument('-s', '--size', type=int, help='number of workspaces per output', default=20)
    parser.add_argument('-p', '--priority', type=str, help='Output priority, <name>:<priority>, e.g. eDP-1:2',
                        action='append', default=[])
    parser.add_argument('-d', '--direction', type=str, help="the output direction",
                        choices=['next', 'prev'], default='next')
    parser.add_argument('-n', '--number', type=int, help='the workspace number')
    parser.add_argument('action', type=str, help='the action to execute',
                        choices=['organize', 'focus_workspace', 'move_current_container_to_workspace', 'focus_output',
                                 'move_current_workspace_to_output', 'move_current_container_to_output',
                                 'insert_current_workspace'])

    args = parser.parse_args()

    action = args.action
    if action == 'organize':
        asyncio.run(organize(args.size, args.priority))
    elif action == 'focus_workspace':
        asyncio.run(focus_workspace(args.size, args.priority, args.number))
    elif action == 'move_current_container_to_workspace':
        asyncio.run(move_current_container_to_workspace(args.size, args.priority, args.number))
    elif action == 'focus_output':
        asyncio.run(focus_output(args.priority, args.direction))
    elif action == 'move_current_workspace_to_output':
        asyncio.run(move_current_workspace_to_output(args.priority, args.direction, args.size))
    elif action == 'move_current_container_to_output':
        asyncio.run(move_current_container_to_output(args.priority, args.direction, args.size))
    elif action == 'insert_current_workspace':
        asyncio.run(insert_current_workspace(args.priority, args.size, args.number))

    # TODO add action for inserting a workspace before another workspace (on the current output)
    # TODO organize arguments into sub-commands
