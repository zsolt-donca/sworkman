#!/usr/bin/python

# sworkman - Sway Workspace Manager

import argparse
import asyncio

from i3ipc.aio import Connection


async def organize(size, priorities):
    i3 = await Connection().connect()
    workspaces = await i3.get_workspaces()
    outputs = await get_outputs_sorted(i3, priorities)

    for outputs_index in range(len(outputs)):
        output = outputs[outputs_index]
        workspaces_in_output = list(filter(lambda x: x.output == output.name, workspaces))
        for workspaces_in_output_index in range(len(workspaces_in_output)):
            workspace = workspaces_in_output[workspaces_in_output_index]
            current_name = workspace.name
            new_num = outputs_index * size + workspaces_in_output_index
            new_name = change_num_in_name(current_name, workspace.num, new_num)
            await i3.command(f'rename workspace "{current_name}" to "{new_name}"')


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

    dest_workspace_num = select_destination_output(dest_output_name, outputs, workspaces)

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
    workspaces_after = await i3.get_workspaces()
    for workspace in workspaces_after:
        workspace_output = workspace.output
        is_workspace_relevant = (workspace_output == orig_output_name or workspace_output == dest_output_name)
        is_only_workspace_on_output = len([w for w in workspaces if w.output == workspace_output]) == 1
        if is_workspace_relevant and is_only_workspace_on_output and is_workspace_empty(workspace):
            for outputs_index in range(len(outputs)):
                output = outputs[outputs_index]
                if output.name == workspace_output:
                    current_name = workspace.name
                    new_num = outputs_index * size
                    new_name = change_num_in_name(current_name, workspace.num, new_num)
                    await i3.command(f'rename workspace "{current_name}" to "{new_name}"')


def select_destination_output(dest_output_name, outputs, workspaces):
    workspaces_by_output = {o.name: [w for w in workspaces if w.output == o.name] for o in outputs}
    # if the destination output has an empty workspace on it, let's move the current workspace over there
    output_matching_workspace_num = [w.num for w in workspaces_by_output[dest_output_name] if is_workspace_empty(w)]
    if len(output_matching_workspace_num) > 0:
        dest_workspace_num = output_matching_workspace_num[0]
    else:
        dest_workspace_num = get_next_workspace_number_for_output(workspaces, dest_output_name)
    return dest_workspace_num


def get_focused_output(outputs):
    focused_outputs = [o for o in outputs if o.focused]
    if len(focused_outputs) == 1:
        return focused_outputs[0]
    else:
        raise Exception(f"bug: could not get focused outputs: {outputs}")


def is_workspace_empty(workspace):
    return not workspace.ipc_data["floating_nodes"] and (
                not workspace.ipc_data["representation"] or workspace.ipc_data["representation"] == "H[]" or
                workspace.ipc_data["representation"] == "V[]" or workspace.ipc_data["representation"] == "S[]")


# moves the current container to a new workspace on the destination output
async def move_current_container_to_output(priorities, direction):
    i3 = await Connection().connect()
    outputs = await get_outputs_sorted(i3, priorities)
    workspaces = await i3.get_workspaces()

    output_name = get_output_for_direction(outputs, direction).name

    dest_workspace_num = select_destination_output(output_name, outputs, workspaces)

    # moves the current container to a new workspace (as workspace named new_workspace_num does not exist)
    await i3.command(f'move container to workspace number {dest_workspace_num}')

    # focus the workspace
    await i3.command(f'workspace number {dest_workspace_num}')

    # this moves the focused workspace to the selected output
    await i3.command(f'move workspace to output {output_name}')


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


# returns the absolute workspace number (e.g. 24) given a relative number (e.g. 4) and size (e.g. 20)
# requires outputs to be sorted (by priority)
def get_workspace_number(outputs, size, number):
    for outputs_index in range(len(outputs)):
        output = outputs[outputs_index]
        if output.focused:
            workspace_number = outputs_index * size + number
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

    for outputs_index in range(len(outputs)):
        output = outputs[outputs_index]
        if output.focused:
            index_at_direction = (outputs_index + offset) % len(outputs)
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
    workspace_nums_in_output =  [w.num for w in workspaces if w.output == output_name]
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
                                 'move_current_workspace_to_output',
                                 'move_current_container_to_output'])

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
        asyncio.run(move_current_container_to_output(args.priority, args.direction))

    # TODO add action for inserting a workspace before another workspace (on the current output)
    # TODO organize arguments into sub-commands
