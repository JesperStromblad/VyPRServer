"""
Module to handle interaction with the verdict database.
"""

# use sqlite for now
import sqlite3
import traceback
import json

database_string = "verdicts.db"

def get_connection():
	# for now, let exceptions appear in the log
	global database_string
	return sqlite3.connect(database_string)

def insert_verdict(verdict_dictionary):
	"""
	Given a verdict dictionary containing a function name,
	time of call, bind space index and verdict (paired with timestamp),
	insert the necessary rows into the tables in the verdict schema.
	"""

	connection = get_connection()
	cursor = connection.cursor()
	# find if the function exists in the database
	results = cursor.execute("select * from function where fully_qualified_name = ? and property = ?", [verdict_dictionary["function_name"], verdict_dictionary["property_hash"]]).fetchall()
	new_function_id = int(results[0][0])

	# create the binding if it doesn't already exist
	results = cursor.execute("select * from binding where binding_space_index = ? and function = ?", [verdict_dictionary["bind_space_index"], new_function_id]).fetchall()
	new_binding_id = int(results[0][0])

	# create the http request
	results = cursor.execute("select * from http_request where time_of_request = ?", [verdict_dictionary["http_request_time"]]).fetchall()
	if len(results) == 0:
		# no binding exists yet, so insert a new binding
		cursor.execute("insert into http_request (time_of_request, grouping) values (?, ?)",
			(verdict_dictionary["http_request_time"], ""))
		connection.commit()
		# get the id
		new_http_request_id = int(cursor.execute("select id from http_request where time_of_request = ?", [verdict_dictionary["http_request_time"]]).fetchall()[0][0])
	else:
		# get the id of the existing http request
		new_http_request_id = int(results[0][0])

	print("verdict data received")
	print(verdict_dictionary["verdict"])

	# insert the function call that the verdict belongs to
	results = cursor.execute("select * from function_call where time_of_call = ? and function = ?", [verdict_dictionary["time_of_call"], new_function_id]).fetchall()
	if len(results) == 0:
		# no binding exists yet, so insert a new binding
		cursor.execute("insert into function_call (function, time_of_call, http_request) values (?, ?, ?)",
			(new_function_id, verdict_dictionary["time_of_call"], new_http_request_id))
		new_function_call_id = cursor.lastrowid
		connection.commit()
	else:
		# get the id of the existing function call
		new_function_call_id = int(results[0][0])

	# now we have a verdict to link observations to, we insert the assignments and the observations
	# process the slice dictionary received and, for any assignment not already existing, create a new one.
	# keeping a record of the IDs of all existing and newly created assignments
	# note: indices of slice_map and observations_map are the same since they're constructed at the same time
	# during monitoring
	#slice_map = verdict_dictionary["verdict"][3]
	observations_map = verdict_dictionary["verdict"][2]
	path_map = verdict_dictionary["verdict"][3]
	path_condition_ids = []

	# find longest path length and just perform insertion for this path
	# all the others will be subpaths
	longest_path_index = verdict_dictionary["verdict"][3].keys()[0]
	for atom_index in path_map:
		if len(verdict_dictionary["verdict"][3][atom_index]) > len(verdict_dictionary["verdict"][3][longest_path_index]):
			longest_path_index = atom_index

	print("atom index %s has longest path" % longest_path_index)

	condition_id_sequence = verdict_dictionary["verdict"][3][longest_path_index]
	# insert empty condition at the beginning - we need to check if the empty condition exists in the database
	result = cursor.execute("select id from path_condition_structure where serialised_condition = ''").fetchall()
	if len(result) > 0:
		# the empty condition exists
		empty_condition_id = int(result[0][0])
	else:
		# we have to insert the empty condition
		cursor.execute("insert into path_condition_structure (serialised_condition) values('')")
		empty_condition_id = int(cursor.lastrowid)
	condition_id_sequence = [empty_condition_id] + condition_id_sequence

	print("performing insertion with condition id sequence %s" % str(condition_id_sequence))

	# before constructing the path based on the atom with the longest path sequence,
	# we trace forwards through condition_id_sequence to see if part of the path has already been inserted
	# by a previous verdict insertion from the same function call.
	# eventually we should change the way verdicts are sent from the service-level to send everything at once
	# and then path insertion will be simpler
	for (n, condition_id) in enumerate(condition_id_sequence):
		print("path check - %i with condition id %i and function call id %i" % (n, condition_id, new_function_call_id))
		result = cursor.execute("select id, next_path_condition from path_condition where serialised_condition = ? and function_call = ?", [condition_id, new_function_call_id]).fetchall()
		if len(result) == 0:
			# the only way this can happen is if there is no existing path - if the first path condition
			# in the chain exists, all others in the chain exist by construction.
			# we tell the path insertion that happens below where to start inserting the path from
			# in this case, the entire path must be inserted because nothing exists yet.

			print("no path found - inserting one")

			most_recent_id = None
			for (m, condition_id) in enumerate(condition_id_sequence[::-1]):
				# insert a new path_condition row for this condition_id
				next_path_condition = -1 if m == 0 else most_recent_id
				cursor.execute("insert into path_condition (serialised_condition, next_path_condition, function_call) values(?, ?, ?)",
					[condition_id, next_path_condition, new_function_call_id])
				print("inserted", condition_id, next_path_condition, new_function_call_id)
				most_recent_id = cursor.lastrowid
				path_condition_ids.append(most_recent_id)

			# reverse the id sequence since it's currently backwards due
			# due to inserting in reverse order
			path_condition_ids = path_condition_ids[::-1]

			break

		else:
			next_path_condition = result[0][1]
			path_condition_ids.append(result[0][0])
			if next_path_condition == -1 and n < len(condition_id_sequence)-1:
				# we've reached the end of the path condition chain, but we have more conditions to insert
				# from the verdict sent from the service-level.
				# this means we must extend the existing path
				# we do this by inserting the rest of the path (the remainder of condition_id_sequence)
				# and then updating the old end of path to point to the new extension

				print("existing path ended too soon - extending it...")
				print("starting by inserting extension from position %i" % (n+1))

				# insert the extension
				most_recent_id = None
				extension_condition_ids = []
				for (m, condition_id) in enumerate(condition_id_sequence[n+1:][::-1]):
					# insert a new path_condition row for this condition_id
					next_path_condition = -1 if m == 0 else most_recent_id
					cursor.execute("insert into path_condition (serialised_condition, next_path_condition, function_call) values(?, ?, ?)",
						[condition_id, next_path_condition, new_function_call_id])
					print("inserted", condition_id, next_path_condition, new_function_call_id)
					most_recent_id = cursor.lastrowid
					extension_condition_ids.append(most_recent_id)

				# reverse the list of condition ids of the path extension
				extension_condition_ids = extension_condition_ids[::-1]
				# add to the existing list of condition ids
				path_condition_ids += extension_condition_ids

				# update the old path
				cursor.execute("update path_condition set next_path_condition = ? where id = ?", [most_recent_id, result[0][0]])

				break

	"""# insert path data
	for atom_index in path_map:
		print("processing atom index %i in path condition insertion" % int(atom_index))
		#atom_index = int(atom_index)
		# insert path condition sequence
		condition_id_sequence = verdict_dictionary["verdict"][3][atom_index]
		# insert empty condition at the beginning - we need to check if the empty condition exists in the database
		result = cursor.execute("select id from path_condition_structure where serialised_condition = ''").fetchall()
		if len(result) > 0:
			# the empty condition exists
			empty_condition_id = int(result[0][0])
		else:
			# we have to insert the empty condition
			cursor.execute("insert into path_condition_structure (serialised_condition) values('')")
			empty_condition_id = int(cursor.lastrowid)
		condition_id_sequence = [empty_condition_id] + condition_id_sequence
		# we iterate in reverse so we know what the ID is for the "next" path condition
		most_recent_id = None
		for (n, condition_id) in enumerate(condition_id_sequence[::-1]):
			# insert a new path_condition row for this condition_id
			next_path_condition = -1 if n == 0 else most_recent_id
			results = cursor.execute("select id from path_condition where serialised_condition = ? and next_path_condition = ? and function_call = ?",
				[condition_id, next_path_condition, new_function_call_id]).fetchall()
			print("for path condition check:", condition_id, next_path_condition, new_function_call_id)
			elif len(results) == 0 and next_path_condition != -1:
				# check for a part of the path with matching condition and function call ids,
				# but with next_path_condition set to -1 (ie, we've reached the end of an existing
				# path, so we need to extend it)
				second_check = cursor.execute("select * from path_condition where serialised_condition = ? and function_call = ? and next_path_condition = -1",
					[condition_id, new_function_call_id]).fetchall()
				if len(second_check) == 0:
					# no end of path was found - we're constructing a path from scratch
					cursor.execute("insert into path_condition (serialised_condition, next_path_condition, function_call) values(?, ?, ?)",
						[condition_id, next_path_condition, new_function_call_id])
					most_recent_id = cursor.lastrowid
				else:
					# end of a path was found - extend it to attach it to this new suffix
					cursor.execute("update path_condition set next_path_condition = ? where serialised_condition = ? and function_call = ?",
						[next_path_condition, condition_id, new_function_call_id])
					most_recent_id = second_check[0][0]
			else:
				most_recent_id = int(results[0][0])
			path_condition_ids.append(most_recent_id)"""
	print("path condition ids are %s" % path_condition_ids)

	# create the verdict
	# we don't check for an existing verdict - there won't be repetitions here
	# we have to create this before inserting slice data because slices map to observations, which map to verdicts
	verdict = verdict_dictionary["verdict"][0]
	verdict_time_obtained = verdict_dictionary["verdict"][1]
	collapsing_atom_index = verdict_dictionary["verdict"][4]
	cursor.execute("insert into verdict (binding, verdict, time_obtained, function_call, collapsing_atom) values (?, ?, ?, ?, ?)",
		[new_binding_id, verdict, verdict_time_obtained, new_function_call_id, collapsing_atom_index])
	new_verdict_id = cursor.lastrowid

	for atom_index in path_map:
		# for now, without transition input data, we just insert observations

		# insert observation for this atom_index
		print(observations_map[atom_index])
		last_condition = path_condition_ids[len(path_map[atom_index])]
		cursor.execute("insert into observation (instrumentation_point, verdict, observed_value, previous_condition) values(?, ?, ?, ?)",
			[observations_map[atom_index][1], new_verdict_id, str(observations_map[atom_index][0]), last_condition])
		observation_id = cursor.lastrowid

	connection.commit()

	connection.close()

def insert_property(property_dictionary):
	"""
	Given a dictionary describing a property (hash + serialised structure), insert into the database.
	"""

	connection = get_connection()
	cursor = connection.cursor()

	try:
		serialised_structure = {
			"bind_variables" : property_dictionary["serialised_bind_variables"],
			"property" : property_dictionary["serialised_formula_structure"]
		}
		serialised_structure = json.dumps(serialised_structure)
		cursor.execute("insert into property (hash, serialised_structure) values (?, ?)", [property_dictionary["formula_hash"], serialised_structure])
	except:
		# for now, the error was probably because of dupicate properties if instrumentation was run again.
		# instrumentation should only ever be run for new versions of code, so at some point
		# we will need to integrate version distinction into the schema.

		print("ERROR OCCURRED DURING INSERTION:")

		traceback.print_exc()

	try:
		atom_index_to_db_index = []
		
		# insert the atoms
		serialised_atom_list = property_dictionary["serialised_atom_list"]
		for pair in serialised_atom_list:
			cursor.execute("insert into atom (property_hash, serialised_structure, index_in_atoms) values (?, ?, ?)",
				[property_dictionary["formula_hash"], pair[1], pair[0]])
			atom_index_to_db_index.append(cursor.lastrowid)

		print(atom_index_to_db_index)

		# insert the function
		cursor.execute("insert into function (fully_qualified_name, property) values (?, ?)", [property_dictionary["function"], property_dictionary["formula_hash"]])
		connection.commit()
		connection.close()
		print("property and function inserted")
		return atom_index_to_db_index, cursor.lastrowid
	except:
		# for now, the error was probably because of dupicate properties if instrumentation was run again.
		# instrumentation should only ever be run for new versions of code, so at some point
		# we will need to integrate version distinction into the schema.

		print("ERROR OCCURRED DURING INSERTION:")

		traceback.print_exc()
		return "failure"


def insert_binding(binding_dictionary):
	"""
	Given a dictionary describing a binding (binding space index, function, lines), insert into the database.
	"""

	connection = get_connection()
	cursor = connection.cursor()

	try:
		print(binding_dictionary)
		cursor.execute("insert into binding (binding_space_index, function, binding_statement_lines) values (?, ?, ?)",
			[binding_dictionary["binding_space_index"], binding_dictionary["function"], json.dumps(binding_dictionary["binding_statement_lines"])])
		new_id = cursor.lastrowid
		connection.commit()
		connection.close()
		return new_id
	except:
		# for now, the error was probably because of dupicate properties if instrumentation was run again.
		# instrumentation should only ever be run for new versions of code, so at some point
		# we will need to integrate version distinction into the schema.

		print("ERROR OCCURRED DURING INSERTION:")

		traceback.print_exc()

		return "failure"


def insert_instrumentation_point(dictionary):
	"""
	Given a dictionary describing an instrumentation point, insert the instrumentation point,
	the atom-instrumentation point and binding-instrumentation point pairs.
	"""

	connection = get_connection()
	cursor = connection.cursor()

	try:
		print(dictionary)
		# TODO: add existence checks
		# insert instrumentation point
		cursor.execute("insert into instrumentation_point (serialised_condition_sequence, reaching_path_length) values (?, ?)",
			[json.dumps(dictionary["serialised_condition_sequence"]), dictionary["reaching_path_length"]])
		new_id = cursor.lastrowid
		
		# insert the atom-instrumentation point link
		cursor.execute("insert into atom_instrumentation_point_pair (atom, instrumentation_point) values (?, ?)", [dictionary["atom"], new_id])

		# insert the binding-instrumentation point link
		cursor.execute("insert into binding_instrumentation_point_pair (binding, instrumentation_point) values (?, ?)", [dictionary["binding"], new_id])

		connection.commit()
		connection.close()
		return new_id
	except:
		# for now, the error was probably because of dupicate properties if instrumentation was run again.
		# instrumentation should only ever be run for new versions of code, so at some point
		# we will need to integrate version distinction into the schema.

		print("ERROR OCCURRED DURING INSERTION:")

		traceback.print_exc()

		return "failure"

def insert_branching_condition(dictionary):
	"""
	Given a dictionary describing a branching condition, perform the insertion.
	"""
	connection = get_connection()
	cursor = connection.cursor()
	try:
		print(dictionary)
		# check for existence
		result = cursor.execute("select * from path_condition_structure where serialised_condition = ?", [dictionary["serialised_condition"]]).fetchall()
		if len(result) > 0:
			# condition already exists - return the existing ID
			return result[0][0]
		else:
			# condition is new - insert it
			cursor.execute("insert into path_condition_structure (serialised_condition) values (?)", [dictionary["serialised_condition"]])
			new_id = cursor.lastrowid
			connection.commit()
			connection.close()
			return new_id
	except:
		print("ERROR OCCURED DURING INSERTION:")
		traceback.print_exc()
		return "failure"

def list_verdicts(function_name):
	"""
	Given a function name, for each http request, for each function call, list the verdicts.
	"""
	connection = get_connection()
	cursor = connection.cursor()

	function_id = cursor.execute("select id from function where fully_qualified_name = ?", [function_name]).fetchall()[0][0]

	bindings = cursor.execute("select * from binding where function = ?", [function_id]).fetchall()

	http_requests = cursor.execute("select * from http_request").fetchall()
	request_to_verdicts = {}
	for result in http_requests:
		request_to_verdicts[result[1]] = {}
		# find the function calls of function_name for this http request
		calls = cursor.execute("select * from function_call where http_request = ?", [result[0]]).fetchall()
		for call in calls:
			request_to_verdicts[result[1]][call[2]] = {}
			for binding in bindings:
				verdicts = cursor.execute("select * from verdict where binding = ? and function_call = ?", [binding[0], call[0]]).fetchall()
				request_to_verdicts[result[1]][call[2]][binding[0]] = verdicts
				truth_map = {1 : True, 0 : False}
				request_to_verdicts[result[1]][call[2]][binding[0]] = map(list, request_to_verdicts[result[1]][call[2]][binding[0]])
				for n in range(len(request_to_verdicts[result[1]][call[2]][binding[0]])):
					request_to_verdicts[result[1]][call[2]][binding[0]][n][1] = truth_map[request_to_verdicts[result[1]][call[2]][binding[0]][n][1]]

	connection.close()

	return request_to_verdicts

def list_http_requests(function_id):
	"""
	Return a list of all http requests - we may eventually want do to this with a time interval bound.
	"""
	connection = get_connection()
	cursor = connection.cursor()

	http_requests = cursor.execute("select * from http_request").fetchall()

	# list only the requests for which there is a call to the function with function_id
	final_requests = []
	for request in http_requests:
		calls_with_function_id = cursor.execute("select * from function_call where function = ? and http_request = ?", [function_id, request[0]]).fetchall()
		if len(calls_with_function_id) > 0:
			final_requests.append(request)

	connection.close()

	return final_requests

def list_calls_during_request(http_request_id, function_name):
	"""
	Given an http request id, list the function calls of the given function during that request.
	"""
	connection = get_connection()
	cursor = connection.cursor()

	function_calls = cursor.execute("select * from function_call where http_request = ? and function = ?", [http_request_id, function_name]).fetchall()

	connection.close()

	return function_calls

def list_verdicts_from_function_call(function_call_id):
	"""
	Given a function call id, return all the verdicts reached during this function call.
	"""
	connection = get_connection()
	cursor = connection.cursor()

	verdicts = cursor.execute("select binding.binding_statement_lines, verdict.verdict, verdict.time_obtained from "+\
		"(verdict inner join binding on verdict.binding=binding.id) where verdict.function_call = ?", [function_call_id]).fetchall()

	connection.close()

	return verdicts

def list_functions():
	"""
	Return a list of all functions found.
	"""

	connection = get_connection()
	cursor = connection.cursor()

	functions = cursor.execute("select function.id, function.fully_qualified_name, function.property, property.serialised_structure from "+\
		"(function inner join property on function.property=property.hash)").fetchall()

	# process the functions into a hierarchy by splitting the function names up by dots
	dictionary_tree_structure = {}
	for function in functions:
		path = function[1].split(".")
		if not(dictionary_tree_structure.get(path[0])):
			dictionary_tree_structure[path[0]] = {}
		current_hierarchy_step = dictionary_tree_structure[path[0]]
		# iterate through the rest of the path
		for item in path[1:-1]:
			if not(current_hierarchy_step.get(item)):
				current_hierarchy_step[item] = {}
			current_hierarchy_step = current_hierarchy_step[item]

		if current_hierarchy_step.get(path[-1]):
			current_hierarchy_step[path[-1]].append(function)
		else:
			current_hierarchy_step[path[-1]] = [function]

	#print(dictionary_tree_structure)

	connection.close()

	return dictionary_tree_structure

def get_http_request_function_call_pairs(verdict, path):
	"""
	For the given verdict and path pair, find all the function calls inside that path that
	result in a verdict matching the one given.

	To do this, we first find all the functions that match the path given.
	"""
	connection = get_connection()
	cursor = connection.cursor()

	path = "%s%%" % path

	truth_map = {"violating" : 0, "not-violating" : 1}

	final_map = {}

	# note that a function is unique wrt a property - so each row returned here is coupled with a single property
	functions = cursor.execute("select * from function where fully_qualified_name like ?", [path]).fetchall()

	# Now, get all the calls to these functions and, for each call, find all the verdicts and organise them by binding

	final_map["functions"] = {}
	for function in functions:
		final_map["functions"][function[0]] = {"calls" : {}, "property" : {}, "fully_qualified_name" : function[1]}
		data_found_for_function = False

		# get the property string representation
		property_id = function[2]
		property_info = json.loads(cursor.execute("select * from property where hash = ?", [property_id]).fetchall()[0][1])
		final_map["functions"][function[0]]["property"] = property_info

		# get the calls
		calls = cursor.execute("select * from function_call where function = ?", [function[0]]).fetchall()
		for call in calls:
			data_found_for_call = False
			final_map["functions"][function[0]]["calls"][call[0]] = {"bindings" : {}, "time" : call[2]}
			bindings = cursor.execute("select * from binding where function = ?", [function[0]]).fetchall()
			for binding in bindings:
				verdicts = cursor.execute("select * from verdict where binding = ? and function_call = ? and verdict = ?", [binding[0], call[0], truth_map[verdict]]).fetchall()
				verdict_tuples = map(lambda row : (row[2], row[3]), verdicts)
				if len(verdict_tuples) > 0:
					final_map["functions"][function[0]]["calls"][call[0]]["bindings"][binding[0]] = {"verdicts" : [], "lines" : binding[3]}
					final_map["functions"][function[0]]["calls"][call[0]]["bindings"][binding[0]]["verdicts"] = verdict_tuples
					data_found_for_call = True
					data_found_for_function = True

			if not(data_found_for_call):
				del final_map["functions"][function[0]]["calls"][call[0]]

		if not(data_found_for_function):
			del final_map["functions"][function[0]]

	return final_map